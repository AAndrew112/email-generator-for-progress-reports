{{include _contract.md}}

TASK (tier 1 extraction). Input: `work/batches/{{BATCH_ID}}.jsonl` (one chunk per line: chunk_id, date, kind,
source_label, text). The author of every chunk is [SUBJECT]. Chat chunks are the subject's own spoken
video messages to friends; journal chunks are handwritten entries transcribed by a machine, so expect
errors and markers like [illegible] and [?word?].

For EVERY chunk, write one JSON object. Output a JSON array to `work/extractions/{{BATCH_ID}}.json`
(one object per input chunk, same order). Schema:

{
 "chunk_id": str,
 "emotions": [{"label": str, "intensity": 1|2|3, "evidence_quote": str<=25 words}],   // emotions the subject names or clearly expresses
 "topics": [str],                                    // up to 5 short noun phrases
 "people": [{"token": "[PERSON_003]", "role_in_text": str, "valence_toward": -2..2,
             "context": "support_given|support_sought|conflict|logistics|humor|worry|celebration|gossip|other"}],
 "commitments": [{"quote": str<=25 words, "kind": "start|stop|change|will_do|resolution", "horizon": str}],
 "predictions": [{"quote": str<=25 words, "about": "self_future_feeling|event|other"}],
 "advice_given": [{"quote": str<=25 words, "domain": str}],
 "self_descriptions": [{"quote": str<=25 words, "valence": -1|0|1}],
 "agency": {"locus": "internal|external|mixed|none", "self_blame": 0|1|2, "externalizing": 0|1|2},
 "conflict": {"present": bool, "role": "initiator|recipient|mediator|observer|none", "repair_attempt": bool},
 "reception_cues": [{"quote": str<=25 words, "who": "[PERSON_003]" or "group", "what": str}],  // the subject quoting or reacting to how others respond
 "values": [str],                                    // up to 3, only if evident
 "sensitive_flag": "none|trauma|abuse|self_harm|crisis|sexual|health|other_person_disclosure",
 "risk_flag": bool,
 "salience": 0|1|2|3,                                // 3 = unusually revealing or pivotal for understanding the subject
 "notes": str                                        // at most 30 words, no quotes of sensitive material
}

RULES
- Every quote must be copied exactly from the chunk text (the validator rejects invented or altered quotes).
  If unsure, omit the item. Empty lists are fine and common.
- Quote nothing when `sensitive_flag` is not "none"; describe in `notes` only.
- Do not infer beyond the text. Do not interpret personality here; extraction records what is said.
- Short, empty or unintelligible chunks: return the object with empty lists and salience 0.
- Do not paste the JSON into your reply.
