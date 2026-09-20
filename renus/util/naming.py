from __future__ import annotations

def to_camel_case(snake_str: str) -> str:
    """Convert a snake_case string to CamelCase.

    Parameters
    ----------
    snake_str:
        A snake_case string to convert (``"user_profile"`` -> ``"UserProfile"``).
    """
    components = snake_str.split("_")
    return "".join(x.title() for x in components)

def to_plural(word: str) -> str:
    """Return the pluralized form of a word, preserving its capitalization.


    Parameters
    ----------
    word:
        The word to pluralize (``"category"`` -> ``"categories"``).
    """
    if not word:
        return word

    lower = word.lower()

    if lower.endswith("y") and len(word) > 1 and lower[-2] not in "aeiou":
        suffix = "IES" if word.isupper() else "ies"
        return word[:-1] + suffix

    if lower.endswith("fe"):
        suffix = "VES" if word.isupper() else "ves"
        return word[:-2] + suffix

    if lower.endswith("f") and not lower.endswith(("ff", "roof", "chef", "cliff")):
        suffix = "VES" if word.isupper() else "ves"
        return word[:-1] + suffix

    if lower.endswith("us") and len(word) > 3 and not lower.endswith("bus"):
        suffix = "I" if word.isupper() else "i"
        return word[:-2] + suffix

    if lower.endswith(("s", "x", "z", "ch", "sh")):
        suffix = "ES" if word.isupper() else "es"
        return word + suffix

    suffix = "S" if word.isupper() else "s"
    return word + suffix

def to_plural_lower(word: str) -> str:
    """Return the pluralized form of a word in lowercase.

    Parameters
    ----------
    word:
        The word to pluralize and lowercase.
    """
    return to_plural(word).lower()
