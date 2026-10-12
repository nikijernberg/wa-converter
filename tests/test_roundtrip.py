import json
import unittest

from fastapi.testclient import TestClient

from forever_translate import format_report, translate_document
from server import app

MINIMAL = {
    "m": "d",
    "s": "5.22.0",
    "v": 89,
    "d": {
        "id": "Web Test",
        "regionType": "icon",
        "triggers": {
            "1": {
                "trigger": {
                    "type": "aura2",
                    "auraspellids": [17],
                    "unit": "player",
                    "debuffType": "HELPFUL",
                }
            }
        },
        "actions": {
            "init": {
                "do_custom": True,
                "custom": "local name = GetSpellInfo(17)\n",
            }
        },
    },
}


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_homepage_puts_forever_to_the_right_of_decode(self):
        html = self.client.get("/").text
        self.assertLess(html.index('id="decode"'), html.index('id="forever"'))
        self.assertIn("To Forever", html)
        self.assertIn("Decode", html)

    def test_encode_decode_and_forever(self):
        encoded = self.client.post("/api/encode", json={"text": json.dumps(MINIMAL)})
        self.assertEqual(encoded.status_code, 200, encoded.text)
        imported = encoded.json()["import_string"]
        self.assertTrue(imported.startswith("!WA:2!"))

        decoded = self.client.post("/api/decode", json={"text": imported})
        self.assertEqual(decoded.status_code, 200, decoded.text)
        aura = json.loads(decoded.json()["json_text"])
        self.assertEqual(aura["d"]["id"], "Web Test")

        converted = self.client.post("/api/forever", json={"text": imported})
        self.assertEqual(converted.status_code, 200, converted.text)
        body = converted.json()
        self.assertIn("C_Spell.GetSpellInfo", body["json_text"])
        self.assertIn("secretAura", body["json_text"])
        self.assertIn("Converted Web Test", body["report"])
        self.assertTrue(body["import_string"].startswith("!WA:2!"))

        again = self.client.post("/api/forever", json={"token": body["token"]})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIn("No old function calls were found", again.json()["report"])

        downloaded = self.client.get(f"/api/files/{body['token']}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("secretAura", downloaded.text)

    def test_missing_input(self):
        response = self.client.post("/api/decode", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Paste a WeakAuras string", response.json()["detail"])


def _doc(aura_id: str, trigger: dict) -> dict:
    return {"m": "d", "d": {"id": aura_id, "triggers": {"1": {"trigger": trigger}}}}


class ForeverRulesTest(unittest.TestCase):
    def test_documented_combat_log_replacements(self):
        document = {
            "m": "d",
            "d": {"id": "Parent", "triggers": {"1": {"trigger": {"type": "aura2", "auranames": ["Power Word: Fortitude"]}}}},
            "c": [
                _doc("Cast", {
                    "type": "combatlog",
                    "event": "Combat Log",
                    "subeventPrefix": "SPELL",
                    "subeventSuffix": "_CAST_SUCCESS",
                    "use_sourceUnit": True,
                    "sourceUnit": "player",
                    "use_spellId": True,
                    "spellId": ["348"],
                })["d"],
                _doc("Hit", {
                    "type": "combatlog",
                    "event": "Combat Log",
                    "subeventPrefix": "SPELL",
                    "subeventSuffix": "_DAMAGE",
                    "use_destUnit": True,
                    "destUnit": "player",
                })["d"],
                _doc("Interrupt", {
                    "type": "combatlog",
                    "event": "Combat Log",
                    "subeventPrefix": "SPELL",
                    "subeventSuffix": "_INTERRUPT",
                    "use_sourceUnit": True,
                    "sourceUnit": "player",
                })["d"],
            ],
        }
        translated, report = translate_document(document)
        triggers = [child["triggers"]["1"]["trigger"] for child in translated["c"]]
        self.assertEqual(triggers[0]["event"], "Spell Cast Succeeded")
        self.assertEqual(triggers[0]["spellId"], ["348"])
        self.assertIn("UNIT_COMBAT:player", triggers[1]["events"])
        self.assertEqual(triggers[2]["event"], "Combat Log")
        text = format_report("Parent", report)
        self.assertIn("Spell Cast Succeeded", text)
        self.assertIn("UNIT_COMBAT:player", text)
        self.assertIn("Interrupt", text)
        self.assertIn("Power Word: Fortitude", text)
        self.assertIn("no equivalent", text)

        again, second = translate_document(translated)
        self.assertEqual(again["c"][0]["triggers"]["1"]["trigger"]["event"], "Spell Cast Succeeded")
        self.assertEqual(second.cast_conversions, [])
        self.assertEqual(second.damage_conversions, [])


if __name__ == "__main__":
    unittest.main()
