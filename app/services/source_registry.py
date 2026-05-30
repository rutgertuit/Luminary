"""Per-job source registry: dedup URLs, number references, render the citation list."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.services.research_stats import increment


def _canonical_url(url: str) -> str:
    """Normalize a URL so trivial variants (case, fragment, query order) collide."""
    s = urlsplit(url.strip())
    netloc = s.netloc.lower()
    query = urlencode(sorted(parse_qsl(s.query, keep_blank_values=True)))
    return urlunsplit((s.scheme.lower() or "https", netloc, s.path or "/", query, ""))


class SourceRegistry:
    def __init__(self) -> None:
        self._by_canonical: dict[str, dict] = {}
        self._order: list[str] = []  # canonical urls in insertion order

    def add(
        self,
        url: str,
        title: str = "",
        snippet: str = "",
        authority: float = 0.0,
        study_index: int = -1,
    ) -> int:
        if not url:
            return 0
        canon = _canonical_url(url)
        entry = self._by_canonical.get(canon)
        if entry is None:
            self._order.append(canon)
            entry = {
                "n": len(self._order),
                "url": url,
                "title": title,
                "snippet": snippet,
                "authority": authority,
                "study_indices": set(),
                "sections": [],
            }
            self._by_canonical[canon] = entry
            increment("registry_urls_added")
        else:
            if not entry["title"] and title:
                entry["title"] = title
            if not entry["snippet"] and snippet:
                entry["snippet"] = snippet
            if entry["authority"] == 0.0 and authority:
                entry["authority"] = authority
            increment("registry_dedup_hits")
        if study_index >= 0:
            entry["study_indices"].add(study_index)
        return entry["n"]

    def record_usage(self, ref_num: int, section: str) -> None:
        for entry in self._by_canonical.values():
            if entry["n"] == ref_num and section not in entry["sections"]:
                entry["sections"].append(section)
                return

    def count_for_study(self, study_index: int) -> int:
        return sum(
            1 for e in self._by_canonical.values()
            if study_index in e["study_indices"]
        )

    def get_reference_list(self) -> list[dict]:
        refs: list[dict] = []
        for canon in self._order:
            e = self._by_canonical[canon]
            refs.append({
                "n": e["n"],
                "url": e["url"],
                "title": e["title"],
                "authority": e["authority"],
                "sections": list(e["sections"]),
            })
        return refs

    def to_dict(self) -> dict:
        return {
            "order": list(self._order),
            "entries": [
                {
                    "canonical": canon,
                    "n": e["n"],
                    "url": e["url"],
                    "title": e["title"],
                    "snippet": e["snippet"],
                    "authority": e["authority"],
                    "study_indices": sorted(e["study_indices"]),
                    "sections": list(e["sections"]),
                }
                for canon, e in self._by_canonical.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRegistry":
        reg = cls()
        reg._order = list(data.get("order", []))
        for e in data.get("entries", []):
            reg._by_canonical[e["canonical"]] = {
                "n": e["n"],
                "url": e["url"],
                "title": e["title"],
                "snippet": e["snippet"],
                "authority": e["authority"],
                "study_indices": set(e.get("study_indices", [])),
                "sections": list(e.get("sections", [])),
            }
        return reg
