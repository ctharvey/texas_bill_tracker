"""The incremental related-bills update must equal a full all-pairs recompute after any sequence of edits."""
from pathlib import Path
import json
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import related_bills as rb


def unit(rng, n=8):
    v = [rng.uniform(-1, 1) for _ in range(n)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def as_state(keys, exclude, raw):
    # Through JSON, as the state file stores it.
    return json.loads(json.dumps({"params": [rb.STATE_FORMAT, rb.MODEL, rb.DIMENSIONS, 3, 0.1], "keys": keys,
                                  "exclude": sorted(sorted(p) for p in exclude),
                                  "best": {i: [[s, o] for s, o in v] for i, v in raw.items()}}))


class IncrementalEqualsFull(unittest.TestCase):
    def test_random_edit_sequences(self):
        for seed in range(40):
            rng = random.Random(seed)
            vectors, keys, exclude = {}, {}, set()
            for i in range(30):
                key = f"k{rng.randrange(26)}"  # some bills share text (same key) on purpose
                vectors.setdefault(key, unit(rng))
                keys[f"B{i}"] = key
            state = None
            for step in range(12):
                raw, recomputed = rb.update_related(state, keys, vectors, exclude, top=3, min_score=0.1)
                full = rb._top_raw(keys, vectors, exclude, top=3, min_score=0.1)
                self.assertEqual(raw, full, f"seed {seed} step {step}")
                state = as_state(keys, exclude, raw)
                # One random edit per step: change a text, add, remove, or toggle a companion pair.
                ids = sorted(keys)
                kind = rng.choice(["text", "add", "remove", "companion", "none"])
                if kind == "text":
                    key = f"n{seed}-{step}"
                    vectors[key] = unit(rng)
                    keys[rng.choice(ids)] = key
                elif kind == "add":
                    key = rng.choice(list(vectors))
                    keys[f"N{seed}-{step}"] = key
                elif kind == "remove" and len(ids) > 5:
                    del keys[rng.choice(ids)]
                elif kind == "companion":
                    a, b = rng.sample(ids, 2)
                    exclude ^= {frozenset((a, b))}

    def test_unchanged_inputs_recompute_no_row(self):
        rng = random.Random(1)
        vectors = {f"k{i}": unit(rng) for i in range(20)}
        keys = {f"B{i}": f"k{i}" for i in range(20)}
        raw, _ = rb.update_related(None, keys, vectors, set(), top=3, min_score=0.1)
        again, recomputed = rb.update_related(as_state(keys, set(), raw), keys, vectors, set(), top=3, min_score=0.1)
        self.assertEqual((again, recomputed), (raw, 0))

    def test_other_parameters_force_a_full_recompute(self):
        rng = random.Random(2)
        vectors = {f"k{i}": unit(rng) for i in range(10)}
        keys = {f"B{i}": f"k{i}" for i in range(10)}
        state = as_state(keys, set(), rb._top_raw(keys, vectors, set(), top=3, min_score=0.1))
        state["params"][3] = 9
        _, recomputed = rb.update_related(state, keys, vectors, set(), top=3, min_score=0.1)
        self.assertEqual(recomputed, -1)

    def test_damaged_state_falls_back_to_the_full_result(self):
        rng = random.Random(4)
        vectors = {f"k{i}": unit(rng) for i in range(12)}
        keys = {f"B{i}": f"k{i}" for i in range(12)}
        full = rb._top_raw(keys, vectors, set(), top=3, min_score=0.1)
        good = as_state(keys, set(), full)
        damage = [
            lambda s: s["best"].__setitem__("B1", [[0.5, "B2", "x"]]),   # 3-element row
            lambda s: s["best"].__setitem__("B1", 5),                    # not a list
            lambda s: s.__setitem__("exclude", [["B1", ["B2"]]]),        # unhashable pair
            lambda s: s["best"].pop("B0"),                               # a bill with no stored list
            lambda s: s["best"].__setitem__("B1", [[0.5, "GHOST"]]),     # unknown id
            lambda s: s["best"].__setitem__("B1", [["nan", "B2"]]),      # not finite
            lambda s: s.__setitem__("keys", []),                         # wrong shape
        ]
        for n, hurt in enumerate(damage):
            state = json.loads(json.dumps(good))
            hurt(state)
            raw, recomputed = rb.update_related(state, keys, vectors, set(), top=3, min_score=0.1)
            self.assertEqual((raw, recomputed), (full, -1), n)

    def test_self_companion_is_not_a_pair(self):
        bills = [{"id": "HB1", "companions": [{"id": "HB1"}, {"id": "SB1"}]}]
        self.assertEqual(rb.companion_pairs(bills), {frozenset(("HB1", "SB1"))})


class PublishKeepsState(unittest.TestCase):
    def test_second_publish_reuses_state_and_matches(self):
        rng = random.Random(3)
        bills = [{"id": f"HB{i}", "caption": f"Relating to topic {i % 7} number {i}."} for i in range(12)]

        def embedder(texts):
            return [unit(rng, rb.DIMENSIONS) for _ in texts], len(texts)

        with tempfile.TemporaryDirectory() as tmp:
            cache, out = Path(tmp) / "cache", Path(tmp) / "related.json"
            rb.publish(bills, {}, cache, out, embedder)
            first = json.loads(out.read_text("utf-8"))
            self.assertTrue((cache / "embeddings" / "related-state.json").is_file())
            mtime = out.stat().st_mtime_ns
            rb.publish(bills, {}, cache, out, embedder)
            self.assertEqual(out.stat().st_mtime_ns, mtime)  # unchanged: not rewritten
            keys = {b["id"]: rb.text_key(rb.bill_text(b, None)) for b in bills}
            vectors = rb.embed_missing([rb.bill_text(b, None) for b in bills], cache, embedder)[0]
            self.assertEqual(first["bills"], rb.top_related(keys, vectors, set()))


if __name__ == "__main__":
    unittest.main()
