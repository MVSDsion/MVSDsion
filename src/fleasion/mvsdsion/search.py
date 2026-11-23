"""Smart search for the Skins tab.

Every word of the query has to match somewhere (name, #tags, gun, includes,
description). Words are matched forgivingly: prefixes, small typos, plurals,
color synonyms (``violet`` finds ``#purple``) and state words such as
``enabled``, ``bought``, ``buy``, ``free`` or ``pinned``. Results are ranked by
how well they match, best first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_WORD = re.compile(r'[\w]+', re.UNICODE)

# Words that mean the same color (both directions are used)
_COLORS: dict[str, tuple[str, ...]] = {
    'red': ('crimson', 'scarlet', 'ruby', 'blood', 'maroon', 'cherry', 'rot'),
    'blue': ('navy', 'azure', 'cobalt', 'sapphire', 'ocean', 'sky', 'blau'),
    'cyan': ('teal', 'turquoise', 'aqua'),
    'green': ('lime', 'emerald', 'mint', 'forest', 'toxic', 'jade', 'grün', 'grun'),
    'purple': ('violet', 'lavender', 'amethyst', 'galaxy', 'lila', 'magenta'),
    'pink': ('rose', 'magenta', 'bubblegum', 'rosa'),
    'yellow': ('gold', 'golden', 'lemon', 'gelb'),
    'orange': ('amber', 'copper', 'tangerine'),
    'black': ('dark', 'shadow', 'onyx', 'midnight', 'void', 'schwarz'),
    'white': ('snow', 'ivory', 'frost', 'pearl', 'weiß', 'weiss'),
    'gray': ('grey', 'silver', 'steel', 'ash', 'grau'),
    'brown': ('wood', 'chocolate', 'bronze', 'braun'),
    'rainbow': ('rgb', 'chroma', 'colorful', 'colourful'),
}
_SYNONYMS: dict[str, set[str]] = {}
for _base, _words in _COLORS.items():
    _group = {_base, *_words}
    for _word in _group:
        _SYNONYMS.setdefault(_word, set()).update(_group - {_word})

# Words that filter by state instead of text
_STATES: dict[str, str] = {
    'enabled': 'enabled', 'enable': 'enabled', 'on': 'enabled', 'active': 'enabled', 'aktiv': 'enabled',
    'disabled': 'disabled', 'off': 'disabled', 'inactive': 'disabled',
    'bought': 'bought', 'owned': 'bought', 'unlocked': 'bought', 'gekauft': 'bought',
    'buy': 'buy', 'locked': 'buy', 'paid': 'buy', 'kaufen': 'buy',
    'free': 'free', 'gratis': 'free', 'kostenlos': 'free',
    'pinned': 'pinned', 'pin': 'pinned', 'favorite': 'pinned', 'favourite': 'pinned', 'fav': 'pinned',
    'custom': 'custom', 'recolor': 'custom', 'colour': 'custom', 'color': 'custom', 'paint': 'custom',
}

# Field weights: a hit in the name counts most
_WEIGHTS = (('name', 5.0), ('tags', 4.5), ('category', 3.0), ('includes', 2.0), ('description', 1.0))


@dataclass(frozen=True, slots=True)
class SearchItem:
    key: str
    name: str
    category: str = ''
    description: str = ''
    includes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    flags: frozenset[str] = field(default_factory=frozenset)


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith('es'):
        return word[:-2]
    if len(word) > 3 and word.endswith('s'):
        return word[:-1]
    return word


def _word_score(query: str, word: str) -> float:
    """How well one query word matches one text word (0 = not at all)."""
    if query == word or _singular(query) == _singular(word):
        return 1.0
    if word.startswith(query):
        return 0.85 if len(query) >= 2 else 0.4
    if word in _SYNONYMS.get(query, ()):
        return 0.75
    if len(query) >= 3 and query in word:
        return 0.6
    if len(query) >= 4 and len(word) >= 4:
        ratio = SequenceMatcher(None, query, word).ratio()
        if ratio >= 0.8:
            return 0.55 * ratio
    return 0.0


def _field_texts(item: SearchItem) -> dict[str, list[str]]:
    return {
        'name': _words(item.name),
        'tags': [tag.casefold().lstrip('#') for tag in item.tags],
        'category': _words(item.category),
        'includes': [word for text in item.includes for word in _words(text)],
        'description': _words(item.description),
    }


def _term_score(term: str, fields: dict[str, list[str]]) -> float:
    best = 0.0
    for name, weight in _WEIGHTS:
        for word in fields[name]:
            score = _word_score(term, word)
            if score:
                best = max(best, score * weight)
                if score == 1.0:
                    break
    return best


def score(query: str, item: SearchItem) -> float:
    """Ranking of ``item`` for ``query``; 0 means it does not match."""
    raw_terms = [term.lstrip('#') for term in query.casefold().split() if term.lstrip('#')]
    if not raw_terms:
        return 1.0
    fields = _field_texts(item)
    total = 0.0
    for raw in raw_terms:
        for term in _words(raw) or [raw]:
            state = _STATES.get(term)
            if state is not None and state in item.flags:
                total += 3.0
                continue
            text_score = _term_score(term, fields)
            if not text_score:
                return 0.0  # Every word has to match (state words filter)
            total += text_score
    # Bonus when the whole query is part of the name
    phrase = ' '.join(raw_terms)
    if phrase in item.name.casefold():
        total += 4.0
    return total


def search(query: str, items: list[SearchItem]) -> list[SearchItem]:
    """Matching items, best first (stable for equal scores)."""
    scored = [(score(query, item), index, item) for index, item in enumerate(items)]
    return [item for value, _index, item in sorted(scored, key=lambda row: (-row[0], row[1])) if value > 0]
