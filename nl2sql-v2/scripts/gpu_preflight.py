"""Check the GPUs a split model will use, before loading it. On Nov 13 the bf16 judge split over two
L40S GPUs computed zeros / NaN / garbage in some jobs and not in others, on the same nodes and inputs,
while one-GPU runs were always right: the suspect is a particular GPU, or GPU pair, in the allocation.
Every visible GPU must multiply correctly (against the CPU) and every ordered pair must copy correctly
peer to peer (against the source bytes); the topology and peer-access flags are printed so a failure
can be traced. Takes seconds."""


def gpu_preflight():
    import subprocess

    import torch
    n = torch.cuda.device_count()
    try:
        print(subprocess.run(["nvidia-smi", "--query-gpu=index,name,pci.bus_id", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout
              + subprocess.run(["nvidia-smi", "topo", "-m"], capture_output=True, text=True).stdout, flush=True)
    except Exception as e:
        print("nvidia-smi:", e, flush=True)
    g = torch.Generator().manual_seed(0)
    x = torch.randn(4097, 2048, generator=g).to(torch.bfloat16)
    w = (torch.randn(2048, 2048, generator=g) / 45).to(torch.bfloat16)
    ref = x.float() @ w.float()
    bad = []
    for i in range(n):
        for _ in range(3):
            y = (x.to(f"cuda:{i}") @ w.to(f"cuda:{i}")).float().cpu()
            if not torch.allclose(y, ref, atol=0.05, rtol=0.02):
                bad.append(f"matmul on gpu {i} (max|diff| {float((y - ref).abs().max()):.3g})")
                break
        src = x.to(f"cuda:{i}")
        for j in range(n):
            if j == i:
                continue
            for _ in range(10):
                got = src.to(f"cuda:{j}").cpu()
                if not torch.equal(got, x):
                    bad.append(f"copy {i}->{j} (zero share {float((got == 0).float().mean()):.3f})")
                    break
    peers = [["-" if i == j else int(torch.cuda.can_device_access_peer(i, j)) for j in range(n)] for i in range(n)]
    print(f"gpu preflight: {n} GPUs, peer access {peers}: "
          + ("every product and copy correct" if not bad else "FAILED " + "; ".join(bad)), flush=True)
    if bad:
        raise SystemExit("gpu preflight failed: " + "; ".join(bad))
