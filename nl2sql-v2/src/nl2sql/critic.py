"""Harness-enforced critic gate: a second model reviews the submission."""

import json
import re
from dataclasses import dataclass

from .config import CriticConfig
from .prompts import CRITIC_PROMPT


@dataclass
class CriticVerdict:
    approve: bool
    feedback: str
    raw: str = ""


def review(client, cfg: CriticConfig, question: str, sql: str, preview_csv: str,
           doc_text: str | None) -> CriticVerdict:
    doc_section = f"\nAttached documentation:\n{doc_text[:8000]}\n" if doc_text else ""
    prompt = CRITIC_PROMPT.format(question=question, doc_section=doc_section,
                                  sql=sql, preview=preview_csv)
    try:
        resp = client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=cfg.temperature, max_tokens=cfg.max_tokens,
            extra_body={"chat_template_kwargs": cfg.chat_template_kwargs}
            if cfg.chat_template_kwargs else None,
        )
        text = resp.choices[0].message.content or ""
    except Exception as e:
        # Critic infra failure must never block a submission.
        return CriticVerdict(approve=True, feedback=f"critic unavailable: {e}")

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return CriticVerdict(approve=True, feedback="critic returned no verdict", raw=text)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return CriticVerdict(approve=True, feedback="critic verdict unparseable", raw=text)

    approve = str(data.get("verdict", "approve")).lower() != "revise"
    issues = data.get("issues") or []
    suggestion = data.get("suggestion") or ""
    feedback = "; ".join(str(i) for i in issues)
    if suggestion:
        feedback = f"{feedback}. Suggestion: {suggestion}" if feedback else suggestion
    return CriticVerdict(approve=approve, feedback=feedback, raw=text)
