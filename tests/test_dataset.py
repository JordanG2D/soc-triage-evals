"""Validate the synthetic data contract, source links and leakage boundary."""

from __future__ import annotations

from collections import Counter
import ipaddress
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"ip_reputation", "user_context", "host_context", "runbook_search"}
TECHNIQUES = {
    "T1059.001", "T1110.003", "T1003.001", "T1053.005",
    "T1041", "T1078", "T1685", "T1105",
}
TARGET_KEYS = {
    "event_truth", "expected_verdict", "severity", "acceptable_technique_ids",
    "required_facts", "tool_policy", "max_tool_calls", "reference_answer",
}
DOCUMENTATION_NETS = [
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]


def load_objects(directory: str) -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text())
        for path in sorted((ROOT / directory).glob("A*.json"))
    }


def all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_keys(child)


class DatasetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alerts = load_objects("data/alerts")
        cls.references = load_objects("data/references")
        cls.context = json.loads((ROOT / "data/tool_context/context.json").read_text())
        cls.runbooks = {
            path.stem: path.read_text()
            for path in sorted((ROOT / "runbooks").glob("*.md"))
        }

    def test_exact_development_slice_and_grouped_variants(self):
        expected = {f"A{i:03}" for i in range(1, 17)}
        self.assertEqual(set(self.alerts), expected)
        self.assertEqual(set(self.references), expected)
        families = Counter(alert["family_id"] for alert in self.alerts.values())
        self.assertEqual(len(families), 8)
        self.assertEqual(set(families.values()), {2})
        for alert_id, alert in self.alerts.items():
            self.assertEqual(alert["id"], alert_id)
            self.assertEqual(self.references[alert_id]["family_id"], alert["family_id"])
            self.assertNotRegex(alert["family_id"], r"malicious|benign|positive|escalation|unknown")
        dataset_doc = (ROOT / "DATASET.md").read_text()
        self.assertIn("not implemented here", dataset_doc)
        self.assertIn("development dataset", dataset_doc)

    def test_alert_shape_and_no_targets_in_model_visible_data(self):
        required = {
            "id", "family_id", "source", "rule", "host", "user", "source_ip",
            "destination_ip", "process", "timestamp", "event",
        }
        for alert in self.alerts.values():
            self.assertEqual(set(alert), required)
            self.assertEqual(set(alert["process"]), {"name", "command_line", "parent"})
            self.assertTrue(alert["event"])
            self.assertRegex(alert["timestamp"], r"^2026-11-10T10:\d{2}:00Z$")
            self.assertFalse(TARGET_KEYS.intersection(all_keys(alert)))
        self.assertFalse(TARGET_KEYS.intersection(all_keys(self.context)))
        for filename in self.runbooks:
            self.assertRegex(filename, r"^RB\d{2}$")

    def test_only_reserved_addresses_and_domains(self):
        texts = [json.dumps(item) for item in self.alerts.values()]
        texts.append(json.dumps(self.context))
        for text in texts:
            for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
                address = ipaddress.ip_address(candidate)
                self.assertTrue(any(address in network for network in DOCUMENTATION_NETS), candidate)
            for domain in re.findall(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.invalid\b", text):
                self.assertTrue(domain.endswith(".example.invalid"), domain)

    def test_context_is_complete_and_has_unique_citable_sources(self):
        self.assertEqual(set(self.context), {"ip_reputation", "user_context", "host_context"})
        identifiers = []
        prefixes = {"ip_reputation": "ip", "user_context": "user", "host_context": "host"}
        for kind, entries in self.context.items():
            for entity, record in entries.items():
                self.assertEqual(record["source_id"], f"{prefixes[kind]}:{entity}")
                self.assertTrue(record["facts"])
                self.assertTrue(all(isinstance(fact, str) and fact.strip() for fact in record["facts"]))
                identifiers.append(record["source_id"])
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for alert in self.alerts.values():
            self.assertIn(alert["host"], self.context["host_context"])
            self.assertIn(alert["user"], self.context["user_context"])
            for field in ("source_ip", "destination_ip"):
                self.assertIn(alert[field], self.context["ip_reputation"])

    def test_reference_shape_and_tool_policy(self):
        required = {
            "alert_id", "family_id", "event_truth", "expected_verdict", "severity",
            "acceptable_technique_ids", "required_facts", "tool_policy",
            "max_tool_calls", "notes",
        }
        genuinely_required = set()
        for alert_id, reference in self.references.items():
            self.assertEqual(set(reference), required)
            self.assertEqual(reference["alert_id"], alert_id)
            self.assertIn(reference["event_truth"], {"malicious", "benign", "unknown"})
            self.assertIn(reference["expected_verdict"], {"true_positive", "benign", "needs_escalation"})
            self.assertIn(reference["severity"], {1, 2, 3, 4})
            self.assertEqual(reference["max_tool_calls"], 6)
            techniques = reference["acceptable_technique_ids"]
            self.assertTrue(techniques)
            self.assertTrue(all(value is None or value in TECHNIQUES for value in techniques))
            policy = reference["tool_policy"]
            self.assertEqual(set(policy), {"required_any_of", "optional", "forbidden"})
            groups = policy["required_any_of"]
            self.assertTrue(all(isinstance(group, list) and group for group in groups))
            needed = {tool for group in groups for tool in group}
            optional, forbidden = set(policy["optional"]), set(policy["forbidden"])
            self.assertFalse(needed & optional)
            self.assertFalse(needed & forbidden)
            self.assertFalse(optional & forbidden)
            self.assertEqual(needed | optional | forbidden, TOOLS)
            genuinely_required |= needed
        self.assertEqual(genuinely_required, TOOLS)

    def test_required_fact_sources_resolve_to_actual_evidence(self):
        source_ids = {f"alert:{alert_id}" for alert_id in self.alerts}
        source_ids |= {record["source_id"] for entries in self.context.values() for record in entries.values()}
        source_ids |= set(self.runbooks)
        for alert_id, reference in self.references.items():
            facts = reference["required_facts"]
            self.assertGreaterEqual(len(facts), 2)
            fact_ids = [fact["id"] for fact in facts]
            self.assertEqual(len(fact_ids), len(set(fact_ids)))
            for fact in facts:
                self.assertEqual(set(fact), {"id", "fact", "supporting_ids"})
                self.assertTrue(fact["fact"].strip())
                self.assertTrue(fact["supporting_ids"])
                self.assertTrue(set(fact["supporting_ids"]) <= source_ids, fact)
                self.assertRegex(fact["id"], f"^{alert_id}-F[1-9]$")
                self.assertFalse(any(source.startswith("alert:") and source != f"alert:{alert_id}" for source in fact["supporting_ids"]))

    def test_truth_is_separate_from_triage_and_technique(self):
        truths = Counter(reference["event_truth"] for reference in self.references.values())
        self.assertEqual(truths, {"malicious": 8, "benign": 6, "unknown": 2})
        techniques = {value for ref in self.references.values() for value in ref["acceptable_technique_ids"] if value is not None}
        self.assertEqual(techniques, TECHNIQUES)
        attack_escalation = self.references["A012"]
        self.assertEqual(attack_escalation["event_truth"], "malicious")
        self.assertEqual(attack_escalation["expected_verdict"], "needs_escalation")
        self.assertEqual(attack_escalation["acceptable_technique_ids"], ["T1041"])
        self.assertTrue(any("RB18" in fact["supporting_ids"] for fact in attack_escalation["required_facts"]))
        for reference in self.references.values():
            if reference["event_truth"] == "unknown":
                self.assertEqual(reference["expected_verdict"], "needs_escalation")
                self.assertEqual(reference["acceptable_technique_ids"], [None])
            if reference["event_truth"] == "benign":
                self.assertEqual(reference["expected_verdict"], "benign")
                self.assertEqual(reference["acceptable_technique_ids"], [None])

    def test_runbooks_are_generic_original_guidance(self):
        self.assertEqual(set(self.runbooks), {f"RB{i:02}" for i in range(1, 31)})
        for identifier, body in self.runbooks.items():
            self.assertTrue(body.startswith("---\n"))
            self.assertIn(f"\nid: {identifier}\n", body)
            self.assertRegex(body, r"\ntitle: [^\n]+\n")
            self.assertIn("\nrelevant_techniques: [", body)
            self.assertNotRegex(body, r"\bA0\d{2}\b")
            self.assertIn("Original guidance", body)
        no_tools = self.references["A011"]["tool_policy"]
        self.assertEqual(no_tools["required_any_of"], [])
        self.assertEqual(set(no_tools["forbidden"]), TOOLS)


if __name__ == "__main__":
    unittest.main()
