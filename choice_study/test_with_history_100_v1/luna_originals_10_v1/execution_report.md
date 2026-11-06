# Luna10 original-only execution

{
  "inspection_id": "8302cda02cf64f3b99cb28c3c3f73a9f2eabda316c653d27dfb568d31fc9791f",
  "requested_model": "gpt-6-luna",
  "job_count": 10,
  "status": "execution_complete",
  "state_counts": {
    "completed": 9,
    "completed_with_validation_errors": 1
  },
  "api_attempts": 10,
  "saved_annotations": 10,
  "structurally_traceable_annotations": 9,
  "returned_models": {
    "gpt-6-luna": 10
  },
  "total_claims": 81,
  "total_rule_objects": 2,
  "rules_potentially_eligible_for_later_testing": 1,
  "model_factual_status_counts": {
    "supported": 39,
    "unsupported_by_supplied_information": 19,
    "contradicted": 12,
    "unclear": 2,
    "not_applicable": 9
  },
  "validation_failures": [
    {
      "job_id": "LUNA10_04__row-2227",
      "issues": [
        "Claim C5: Quote is not an exact nonempty substring"
      ]
    }
  ],
  "review_warnings": [
    {
      "job_id": "LUNA10_04__row-2227",
      "warnings": [],
      "claim_warnings": [
        {
          "claim_id": "C5",
          "warnings": [
            "Historical relationship needs linked purchase and offer fields; review mapping"
          ]
        }
      ]
    },
    {
      "job_id": "LUNA10_06__row-686",
      "warnings": [],
      "claim_warnings": [
        {
          "claim_id": "C6",
          "warnings": [
            "Historical relationship needs linked purchase and offer fields; review mapping"
          ]
        },
        {
          "claim_id": "C13",
          "warnings": [
            "Historical relationship needs linked purchase and offer fields; review mapping"
          ]
        }
      ]
    },
    {
      "job_id": "LUNA10_07__row-495",
      "warnings": [
        "Inspect decisive claims without a corresponding rule entry"
      ],
      "claim_warnings": []
    },
    {
      "job_id": "LUNA10_08__row-215",
      "warnings": [],
      "claim_warnings": [
        {
          "claim_id": "C5",
          "warnings": [
            "Historical relationship needs linked purchase and offer fields; review mapping"
          ]
        }
      ]
    }
  ],
  "truncated_API_responses": 0,
  "model_reports_complete_claim_coverage": 10,
  "usage_totals": {
    "input_tokens": 50038,
    "output_tokens": 87129,
    "total_tokens": 137167,
    "reasoning_tokens": 68915,
    "cached_input_tokens": 33048
  },
  "predictor_calls_added": 0,
  "edited_response_annotations": 0,
  "other_originals_annotated": 0,
  "original_annotation_coverage": {
    "saved": 10,
    "structurally_traceable": 9,
    "selected_originals_in_study": 100
  },
  "edited_annotation_coverage": {
    "annotated": 0,
    "edited_responses_in_study": 642
  },
  "semantic_correctness_checked": false,
  "coverage_verified": false,
  "human_reviewed": false,
  "existing_source_files_preserved": 1658
}

All records are model-generated, not human-reviewed. Structural checks do not establish semantic correctness or complete claim coverage. Existing predictors, prompts, original records and prior annotations are unchanged. No edited annotations or counterfactual rule-consistency/stale-fact metrics were generated.
