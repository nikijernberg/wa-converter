"""Rewrite a decoded WeakAuras document for the WoW: Forever client."""

import json
import re
from dataclasses import dataclass, field

# Call-site wrappers keep the old multiple return values. C_Spell.GetSpellInfo
# returns one table, so a plain rename would break `local name, _, icon = GetSpellInfo(id)`.
_WRAPPERS = {
    "GetSpellInfo": (
        "(function(spell) local info = C_Spell.GetSpellInfo(spell) if not info then return end "
        "return info.name, nil, info.iconID, info.castTime, info.minRange, info.maxRange, info.spellID, info.originalIconID end)"
    ),
    "GetSpellCooldown": (
        "(function(spell) local info = C_Spell.GetSpellCooldown(spell) if not info then return 0, 0, false end "
        "if type(info) ~= \"table\" then return info end "
        "return info.startTime, info.duration, info.isEnabled, info.modRate end)"
    ),
    "GetSpellCharges": (
        "(function(spell) local info = C_Spell.GetSpellCharges(spell) if not info then return end "
        "if type(info) ~= \"table\" then return info end "
        "return info.currentCharges, info.maxCharges, info.cooldownStartTime, info.cooldownDuration, info.chargeModRate end)"
    ),
    "IsUsableSpell": (
        "(function(spell) local usable, noPower = C_Spell.IsSpellUsable(spell) return usable, noPower end)"
    ),
    "UnitBuff": (
        "(function(unit, indexOrName, arg3, arg4) local data "
        "if type(indexOrName) == \"number\" then data = C_UnitAuras.GetBuffDataByIndex(unit, indexOrName, arg3) "
        "else local filter = type(arg4) == \"string\" and arg4 or (type(arg3) == \"string\" and arg3 or \"HELPFUL\") "
        "data = C_UnitAuras.GetAuraDataBySpellName(unit, indexOrName, filter) end "
        "if not data then return end return data.name, data.icon, data.applications, data.dispelName, data.duration, "
        "data.expirationTime, data.sourceUnit, data.isStealable, data.nameplateShowPersonal, data.spellId, "
        "data.canApplyAura, data.isBossAura, data.isFromPlayerOrPlayerPet, data.nameplateShowAll, data.timeMod end)"
    ),
    "UnitDebuff": (
        "(function(unit, indexOrName, arg3, arg4) local data "
        "if type(indexOrName) == \"number\" then data = C_UnitAuras.GetDebuffDataByIndex(unit, indexOrName, arg3) "
        "else local filter = type(arg4) == \"string\" and arg4 or (type(arg3) == \"string\" and arg3 or \"HARMFUL\") "
        "data = C_UnitAuras.GetAuraDataBySpellName(unit, indexOrName, filter) end "
        "if not data then return end return data.name, data.icon, data.applications, data.dispelName, data.duration, "
        "data.expirationTime, data.sourceUnit, data.isStealable, data.nameplateShowPersonal, data.spellId, "
        "data.canApplyAura, data.isBossAura, data.isFromPlayerOrPlayerPet, data.nameplateShowAll, data.timeMod end)"
    ),
    "UnitAura": (
        "(function(unit, index, filter) local data = C_UnitAuras.GetAuraDataByIndex(unit, index, filter) "
        "if not data then return end return data.name, data.icon, data.applications, data.dispelName, data.duration, "
        "data.expirationTime, data.sourceUnit, data.isStealable, data.nameplateShowPersonal, data.spellId, "
        "data.canApplyAura, data.isBossAura, data.isFromPlayerOrPlayerPet, data.nameplateShowAll, data.timeMod end)"
    ),
}

_RENAMES = {
    "GetSpellTexture": "C_Spell.GetSpellTexture",
    "GetSpellName": "C_Spell.GetSpellName",
    "GetSpellLink": "C_Spell.GetSpellLink",
    "GetSpellDescription": "C_Spell.GetSpellDescription",
    "GetSpellSubtext": "C_Spell.GetSpellSubtext",
    "GetItemInfo": "C_Item.GetItemInfo",
    "GetItemInfoInstant": "C_Item.GetItemInfoInstant",
    "GetItemCount": "C_Item.GetItemCount",
    "GetItemIcon": "C_Item.GetItemIcon",
    "GetItemSpell": "C_Item.GetItemSpell",
}

_CALLS = {
    name: re.compile(rf"(?<![\w.]){name}\s*\(")
    for name in (*_WRAPPERS, *_RENAMES, "CombatLogGetCurrentEventInfo")
}
_COMBAT_LOG_EVENT = re.compile(r"COMBAT_LOG_EVENT_UNFILTERED")


ABSORB_CUSTOM = """function(event, unit)
  if unit and unit ~= "player" then
    return false
  end
  local absorb = UnitGetTotalAbsorbs("player")
  if issecretvalue and issecretvalue(absorb) then
    return true
  end
  return absorb and absorb > 0
end
"""

ABSORB_DURATION = """function()
  return UnitGetTotalAbsorbs("player"), UnitHealthMax("player"), true
end
"""

ABSORB_TEXT = """function()
  return UnitGetTotalAbsorbs("player")
end
"""

_SHIELD_WORDS = ("shield", "absorb", "spell_absorbed", "sköld")
_AURA_SUFFIXES = {
    "_AURA_APPLIED",
    "_AURA_REMOVED",
    "_AURA_REFRESH",
    "_AURA_APPLIED_DOSE",
    "_AURA_REMOVED_DOSE",
    "_AURA_BROKEN",
}
_LIVE_CONDITION_PROPERTIES = {"alpha", "color", "desaturate"}

DAMAGE_CUSTOM = """function(event, unit, action)
  if unit and unit ~= "player" then
    return false
  end
  if issecretvalue and issecretvalue(action) then
    return false
  end
  return action == "WOUND"
end
"""


@dataclass
class ForeverReport:
    rewrites: dict[str, int] = field(default_factory=dict)
    absorb_conversions: list[str] = field(default_factory=list)
    modern_auras: list[str] = field(default_factory=list)
    cast_conversions: list[str] = field(default_factory=list)
    damage_conversions: list[str] = field(default_factory=list)
    combat_log: list[str] = field(default_factory=list)
    spell_damage: list[str] = field(default_factory=list)
    frozen_auras: list[str] = field(default_factory=list)
    spell_names: list[str] = field(default_factory=list)
    combat_log_code: list[str] = field(default_factory=list)
    health_thresholds: list[str] = field(default_factory=list)
    foreign_casts: list[str] = field(default_factory=list)
    hidden_names: list[str] = field(default_factory=list)
    frozen_conditions: list[str] = field(default_factory=list)
    chat_blocked: list[str] = field(default_factory=list)
    nameplates: list[str] = field(default_factory=list)

    def add_rewrite(self, name: str, count: int) -> None:
        if count:
            self.rewrites[name] = self.rewrites.get(name, 0) + count


def _aura_name(aura: dict, fallback: str) -> str:
    aura_id = aura.get("id")
    return aura_id if isinstance(aura_id, str) and aura_id else fallback


def _names_from(value) -> list[str]:
    if isinstance(value, str) and value and not value.isdigit():
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item and not item.isdigit()]
    return []


def _uses_combat_log(text: str) -> bool:
    return "COMBAT_LOG_EVENT_UNFILTERED" in text or "CombatLogGetCurrentEventInfo" in text


def _shieldish(aura_name: str, blob: str) -> bool:
    text = f"{aura_name}\n{blob}".lower()
    return any(word in text for word in _SHIELD_WORDS)


def _id_list(value) -> list:
    if isinstance(value, dict):
        if value and all(item is True for item in value.values()):
            return [key for key in value if key not in (None, "")]
        return [item for item in value.values() if item not in (None, "", False)]
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", False)]
    if value not in (None, "", False):
        return [value]
    return []


def _spell_ids(trigger: dict) -> list:
    found = []
    found.extend(_id_list(trigger.get("auraspellids")))
    for key in ("spellId", "spellID", "spellIds"):
        if trigger.get(f"use_{key}") is False:
            continue
        found.extend(_id_list(trigger.get(key)))
    return [spell_id for spell_id in found if spell_id not in (None, "")]


def _used_spell_ids(trigger: dict) -> list:
    if trigger.get("use_spellId") is False and trigger.get("use_spellIds") is False:
        return []
    if trigger.get("use_spellId") or trigger.get("use_spellIds") or trigger.get("spellId") or trigger.get("spellIds"):
        return _spell_ids(trigger)
    return []


def _is_combat_trigger(trigger: dict, blob: str) -> bool:
    return (
        trigger.get("type") == "combatlog"
        or trigger.get("event") == "Combat Log"
        or _uses_combat_log(blob)
    )


def _absorb_trigger() -> dict:
    return {
        "type": "custom",
        "custom_type": "event",
        "check": "event",
        "events": "UNIT_ABSORB_AMOUNT_CHANGED:player",
        "unit": "player",
        "custom": ABSORB_CUSTOM,
        "customDuration": ABSORB_DURATION,
        "custom_hide": "custom",
    }


def _damage_trigger() -> dict:
    return {
        "type": "custom",
        "custom_type": "event",
        "check": "event",
        "events": "UNIT_COMBAT:player",
        "unit": "player",
        "custom": DAMAGE_CUSTOM,
        "custom_hide": "timed",
        "duration": "1",
    }


def _convert_combat_log(aura_name: str, trigger: dict, report: ForeverReport) -> bool:
    """Replace a combat log trigger when Musca documents an equivalent. Leave the rest."""
    if trigger.get("type") != "combatlog" and trigger.get("event") != "Combat Log":
        return False
    prefix = trigger.get("subeventPrefix") or ""
    suffix = trigger.get("subeventSuffix") or ""
    spell_ids = _used_spell_ids(trigger)
    source_is_player = trigger.get("use_sourceUnit") and trigger.get("sourceUnit") == "player"
    dest_is_player = trigger.get("use_destUnit") and trigger.get("destUnit") == "player"
    dest_unit = trigger.get("destUnit") if trigger.get("use_destUnit") else None

    if suffix in _AURA_SUFFIXES and spell_ids and dest_unit:
        trigger.clear()
        trigger.update({
            "type": "secretAura",
            "useExactSpellId": True,
            "auraspellids": spell_ids,
            "unit": dest_unit,
            "debuffType": "BOTH",
        })
        report.modern_auras.append(aura_name)
        return True

    if prefix == "SPELL" and suffix == "_CAST_SUCCESS" and source_is_player:
        duration = trigger.get("duration") or "1"
        replacement = {
            "type": "event",
            "event": "Spell Cast Succeeded",
            "unit": "player",
            "use_unit": True,
            "duration": duration,
        }
        if spell_ids:
            replacement["spellId"] = spell_ids
            replacement["use_spellId"] = True
        trigger.clear()
        trigger.update(replacement)
        report.cast_conversions.append(aura_name)
        return True

    is_damage = suffix.endswith("_DAMAGE")
    if is_damage and dest_is_player:
        if spell_ids:
            report.spell_damage.append(aura_name)
            return False
        duration = trigger.get("duration") or "1"
        replacement = _damage_trigger()
        replacement["duration"] = duration
        trigger.clear()
        trigger.update(replacement)
        report.damage_conversions.append(aura_name)
        return True

    return False


def _note_trigger_limits(aura_name: str, trigger: dict, report: ForeverReport) -> None:
    event = trigger.get("event")
    if event in ("Health", "Power") and any(
        trigger.get(flag) for flag in ("use_percenthealth", "use_health", "use_percentpower", "use_power", "use_deficit")
    ):
        report.health_thresholds.append(aura_name)
    unit = trigger.get("unit")
    if event == "Cast" and unit not in (None, "", "player", "pet"):
        report.foreign_casts.append(aura_name)
    if event == "Unit Characteristics" and any(trigger.get(flag) for flag in ("use_name", "use_npcId", "use_npcID")):
        report.hidden_names.append(aura_name)
    if isinstance(event, str) and event.startswith("Chat"):
        report.chat_blocked.append(aura_name)
    if trigger.get("use_spellNames") and not _used_spell_ids(trigger):
        names = _names_from(trigger.get("spellNames"))
        if names:
            report.spell_names.append(f"{aura_name}: {', '.join(names[:4])}")


def _convert_trigger(aura_name: str, trigger: dict, report: ForeverReport) -> bool:
    blob = json.dumps(trigger, ensure_ascii=False)
    combat = _is_combat_trigger(trigger, blob)
    if combat and _shieldish(aura_name, blob):
        trigger.clear()
        trigger.update(_absorb_trigger())
        report.absorb_conversions.append(aura_name)
        return True
    if trigger.get("type") == "aura2":
        spell_ids = _spell_ids(trigger)
        if spell_ids:
            trigger["type"] = "secretAura"
            trigger["useExactSpellId"] = True
            trigger["auraspellids"] = spell_ids
            trigger["unit"] = trigger.get("unit") or "player"
            trigger["debuffType"] = trigger.get("debuffType") or "HELPFUL"
            report.modern_auras.append(aura_name)
        else:
            report.frozen_auras.append(aura_name)
            names = _names_from(trigger.get("auranames"))
            if names:
                report.spell_names.append(f"{aura_name}: {', '.join(names[:4])}")
    elif trigger.get("use_spellName") and not trigger.get("spellId"):
        names = _names_from(trigger.get("spellName"))
        if names:
            report.spell_names.append(f"{aura_name}: {', '.join(names[:4])}")
    if combat and not _convert_combat_log(aura_name, trigger, report) and aura_name not in report.spell_damage:
        report.combat_log.append(aura_name)
    events = trigger.get("events")
    if isinstance(events, str) and _COMBAT_LOG_EVENT.search(events) and aura_name not in report.absorb_conversions:
        report.combat_log_code.append(aura_name)
    _note_trigger_limits(aura_name, trigger, report)
    return False


def _rewrite_code(code: str, aura_name: str, report: ForeverReport) -> str:
    if "CombatLogGetCurrentEventInfo" in code and _CALLS["CombatLogGetCurrentEventInfo"].search(code):
        report.combat_log_code.append(aura_name)
    if _COMBAT_LOG_EVENT.search(code):
        report.combat_log_code.append(aura_name)
    for name, wrapper in _WRAPPERS.items():
        updated, count = _CALLS[name].subn(wrapper + "(", code)
        report.add_rewrite(name, count)
        code = updated
    for name, modern in _RENAMES.items():
        updated, count = _CALLS[name].subn(modern + "(", code)
        report.add_rewrite(name, count)
        code = updated
    return code


def _replace_shield_code(key: str, value: str, aura_name: str, report: ForeverReport) -> str | None:
    if not _uses_combat_log(value) or not _shieldish(aura_name, value):
        return None
    looks_like_code = (
        key in {"events", "custom", "customDuration", "customText", "customTrigger", "customUntrigger"}
        or value.lstrip().startswith("function")
        or "CombatLogGetCurrentEventInfo" in value
    )
    if not looks_like_code:
        return None
    report.absorb_conversions.append(aura_name)
    if key == "events":
        return "UNIT_ABSORB_AMOUNT_CHANGED:player"
    if key == "customDuration":
        return ABSORB_DURATION
    if "text" in key.lower():
        return ABSORB_TEXT
    return ABSORB_CUSTOM


def _walk(node, aura_name: str, report: ForeverReport) -> None:
    if isinstance(node, dict):
        trigger = node.get("trigger")
        if isinstance(trigger, dict) and ("type" in trigger or "event" in trigger):
            _convert_trigger(aura_name, trigger, report)
        for key, value in list(node.items()):
            if isinstance(value, str):
                replaced = _replace_shield_code(key, value, aura_name, report)
                node[key] = replaced if replaced is not None else _rewrite_code(value, aura_name, report)
            else:
                _walk(value, aura_name, report)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                node[index] = _rewrite_code(value, aura_name, report)
            else:
                _walk(value, aura_name, report)


def _auras(document: dict):
    display = document.get("d")
    if isinstance(display, dict):
        yield display
    children = document.get("c")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                yield child


def load_aura_document(text: str) -> tuple[dict, str]:
    """Return the aura document and the JSON text to encode."""
    parsed = json.loads(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("d"), dict):
        return parsed, text
    if isinstance(parsed, dict) and isinstance(parsed.get("triggers"), (dict, list)):
        wrapped = {"m": "d", "s": "5.22.0", "v": 89, "d": parsed}
        pretty = json.dumps(wrapped, indent=2, ensure_ascii=False) + "\n"
        return wrapped, pretty
    raise ValueError("JSON does not contain an aura. Open a decoded export, or an aura that contains triggers.")


def _note_aura_limits(aura: dict, aura_name: str, report: ForeverReport) -> None:
    if aura.get("anchorFrameType") == "NAMEPLATE":
        report.nameplates.append(aura_name)
    conditions = aura.get("conditions")
    if not isinstance(conditions, list):
        return
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        for change in condition.get("changes") or []:
            if not isinstance(change, dict):
                continue
            prop = change.get("property")
            if isinstance(prop, str) and prop not in _LIVE_CONDITION_PROPERTIES:
                report.frozen_conditions.append(aura_name)
                return


def translate_document(document: dict) -> tuple[dict, ForeverReport]:
    report = ForeverReport()
    for aura in _auras(document):
        aura_name = _aura_name(aura, "Aura")
        _walk(aura, aura_name, report)
        _note_aura_limits(aura, aura_name, report)
    report.absorb_conversions = list(dict.fromkeys(report.absorb_conversions))
    report.modern_auras = list(dict.fromkeys(report.modern_auras))
    report.cast_conversions = list(dict.fromkeys(report.cast_conversions))
    report.damage_conversions = list(dict.fromkeys(report.damage_conversions))
    solved = set(report.absorb_conversions) | set(report.modern_auras) | set(report.cast_conversions) | set(report.damage_conversions)
    report.combat_log = [name for name in dict.fromkeys(report.combat_log) if name not in solved and name not in report.spell_damage]
    report.spell_damage = list(dict.fromkeys(report.spell_damage))
    report.frozen_auras = list(dict.fromkeys(report.frozen_auras))
    report.spell_names = list(dict.fromkeys(report.spell_names))
    report.combat_log_code = list(dict.fromkeys(report.combat_log_code))
    report.health_thresholds = list(dict.fromkeys(report.health_thresholds))
    report.foreign_casts = list(dict.fromkeys(report.foreign_casts))
    report.hidden_names = list(dict.fromkeys(report.hidden_names))
    report.frozen_conditions = list(dict.fromkeys(report.frozen_conditions))
    report.chat_blocked = list(dict.fromkeys(report.chat_blocked))
    report.nameplates = list(dict.fromkeys(report.nameplates))
    return document, report


def _sample(names: list[str], limit: int = 8) -> str:
    shown = names[:limit]
    extra = len(names) - len(shown)
    text = ", ".join(shown)
    if extra > 0:
        text += f" and {extra} more"
    return text


def format_report(aura_name: str, report: ForeverReport) -> str:
    lines = [f"Converted {aura_name} for WoW: Forever.", ""]
    if report.rewrites:
        lines.append("Old function calls were rewritten:")
        for name, count in sorted(report.rewrites.items()):
            lines.append(f"- {name}: {count}")
        lines.append("")
    else:
        lines.append("No old function calls were found in the code.")
        lines.append("")

    if report.absorb_conversions:
        lines.append(
            "Shields that read the combat log now use UnitGetTotalAbsorbs. "
            "That value updates in combat, and the bar can still be drawn when the number is hidden:"
        )
        lines.append(f"- {_sample(report.absorb_conversions)}")
        lines.append("")
    if report.modern_auras:
        lines.append("The Aura trigger was changed to Aura (Modern), so the buff keeps updating in combat:")
        lines.append(f"- {_sample(report.modern_auras)}")
        lines.append("")
    if report.cast_conversions:
        lines.append("Your successful casts now use Spell Cast Succeeded. That event still runs on Forever:")
        lines.append(f"- {_sample(report.cast_conversions)}")
        lines.append("")
    if report.damage_conversions:
        lines.append(
            "Damage taken now uses UNIT_COMBAT:player. Forever has no combat log, and this alert fires for any hit on you:"
        )
        lines.append(f"- {_sample(report.damage_conversions)}")
        lines.append("")

    limits = []
    if report.combat_log:
        limits.append(
            f"Combat Log trigger in {_sample(report.combat_log)}. Forever closes the combat log, and this one has no equivalent event. "
            "Aura gains can become Aura (Modern) only with a unit and a spell ID. Your casts can become Spell Cast Succeeded only when the source is Player."
        )
    if report.spell_damage:
        limits.append(
            f"Damage filtered by spell ID in {_sample(report.spell_damage)}. UNIT_COMBAT does not say which spell hit, so the filter cannot be rebuilt."
        )
    if report.combat_log_code:
        limits.append(
            f"Custom code reads the combat log in {_sample(report.combat_log_code)}. That call does not exist on Forever."
        )
    if report.frozen_auras:
        limits.append(
            f"Classic Aura trigger in {_sample(report.frozen_auras)}. Buffs and debuffs freeze in combat. Aura (Modern) needs a spell ID, and a name alone is ignored."
        )
    if report.spell_names:
        limits.append(
            "Spells entered by name instead of spell ID: " + _sample(report.spell_names, 6) + ". Every rank has its own ID on Forever."
        )
    if report.health_thresholds:
        limits.append(
            f"Health or power percent check in {_sample(report.health_thresholds)}. The bar still moves in combat, but the comparison keeps its last result. Show only below (%) can hide the aura in combat, and that option was not copied."
        )
    if report.foreign_casts:
        limits.append(
            f"Cast trigger on another unit in {_sample(report.foreign_casts)}. Other players' casts are hidden in instances."
        )
    if report.hidden_names:
        limits.append(
            f"Name or NPC ID check in {_sample(report.hidden_names)}. Enemy names and IDs are hidden in instances."
        )
    if report.frozen_conditions:
        limits.append(
            f"A condition in {_sample(report.frozen_conditions)} changes more than alpha, color, or desaturation. Sounds, glows, and other changes wait until combat ends."
        )
    if report.chat_blocked:
        limits.append(
            f"Chat trigger in {_sample(report.chat_blocked)}. Chat messages can be blocked during encounters and PvP."
        )
    if report.nameplates:
        limits.append(
            f"Nameplate anchor in {_sample(report.nameplates)}. It only follows the default Blizzard nameplates. Plater, ElvUI, and Kui replace those frames."
        )
    limits.append("A Retail spell ID can be the wrong rank on Forever. Check the ID if the aura does not show.")
    lines.append("This cannot be fixed automatically:")
    lines.extend(f"- {item}" for item in limits)
    lines.append("")
    lines.append("The import string is copied. Paste it into WeakAuras with Import.")
    return "\n".join(lines)
