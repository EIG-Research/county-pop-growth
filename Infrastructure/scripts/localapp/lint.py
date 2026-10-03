"""Finding and result types shared by the war-room and review-board linters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    code: str
    subject: str | None      # what the finding is about: a block id, an item, a file
    message: str

    def line(self) -> str:
        where = f"{self.subject} " if self.subject else ""
        return f"{self.code}: {where}{self.message}"

    def as_dict(self) -> dict:
        return {"code": self.code, "subject": self.subject, "message": self.message}


@dataclass
class LintResult:
    failures: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def codes(self) -> set[str]:
        return {f.code for f in self.failures}

    def fail(self, code: str, subject: str | None, message: str) -> None:
        self.failures.append(Finding(code, subject, message))

    def warn(self, code: str, subject: str | None, message: str) -> None:
        self.warnings.append(Finding(code, subject, message))

    def as_dict(self) -> dict:
        return {"ok": self.ok,
                "failures": [f.as_dict() for f in self.failures],
                "warnings": [w.as_dict() for w in self.warnings]}
