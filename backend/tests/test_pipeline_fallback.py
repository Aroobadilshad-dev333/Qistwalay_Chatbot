import unittest
from unittest.mock import patch

import pipeline
from text2sql_module import (
    RESTRICTED_COLUMNS,
    SYSTEM_PROMPT,
    get_bankruptcy_eligibility_counts,
    get_applicant_rejection_basis_record,
    get_rejected_sample_list_limit,
    get_sanitized_sample_records,
    get_top_eligible_sample_records,
    is_safe_query,
    is_bankruptcy_eligibility_question,
    is_rejected_sample_list_question,
    is_applicant_rejection_basis_question,
    is_sample_rejection_basis_question,
    run_query,
    text_to_sql,
)


class PipelineFallbackTests(unittest.TestCase):
    def test_rejected_applicant_list_uses_stored_rejected_status(self):
        question = "aaisy person jo nhi ly skty installment pr chiz onka name btao"
        self.assertTrue(is_rejected_sample_list_question(question))
        sql = text_to_sql(question)
        self.assertIn("eligibility_status = 'Rejected'", sql)
        for column in (
            "full_name",
            "monthly_net_income_pkr",
            "avg_monthly_balance_pkr",
            "active_loans_count",
            "late_payments_12m",
            "bounced_cheques_12m",
            "bureau_status",
            "bankruptcy_flag",
            "eligibility_status",
        ):
            self.assertIn(column, sql)
        self.assertNotIn("risk_tier", sql)
        self.assertNotIn("city", sql)
        self.assertFalse(any(token in sql for token in ("credit_score", "decision_reason")))
        limited_question = "Jo 5 person koi cheez installment par nahi le sakte"
        self.assertTrue(is_rejected_sample_list_question(limited_question))
        self.assertEqual(get_rejected_sample_list_limit(limited_question), 5)
        self.assertIn("LIMIT 5", text_to_sql(limited_question))
        self.assertIsNone(get_rejected_sample_list_limit(question))

    def test_rejected_decision_basis_uses_only_allowed_sample_fields(self):
        question = "or kis basis pr tm decide krty ho koi person installment pr chiz nhi ly skta"
        self.assertTrue(is_sample_rejection_basis_question(question))
        sql = text_to_sql(question)
        for column in (
            "eligibility_status",
            "monthly_gross_income_pkr",
            "monthly_net_income_pkr",
            "avg_monthly_balance_pkr",
            "active_loans_count",
            "total_outstanding_debt_pkr",
            "late_payments_12m",
            "bounced_cheques_12m",
            "bureau_status",
            "bankruptcy_flag",
        ):
            self.assertIn(column, sql)
        self.assertIn("eligibility_status = 'Rejected'", sql)
        self.assertNotIn("risk_tier", sql)
        self.assertFalse(any(token in sql for token in ("credit_score", "decision_reason")))

    def test_specific_rejection_basis_query_uses_only_requested_fields_and_status(self):
        questions = (
            "Why was APP-2026-1003 rejected for installments?",
            "APP-2026-1003 ko qist par kyun reject kiya?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_applicant_rejection_basis_question(question))
                sql = text_to_sql(question)

                for column in (
                    "monthly_gross_income_pkr",
                    "monthly_net_income_pkr",
                    "avg_monthly_balance_pkr",
                    "active_loans_count",
                    "total_outstanding_debt_pkr",
                    "late_payments_12m",
                    "bounced_cheques_12m",
                    "bureau_status",
                    "bankruptcy_flag",
                    "eligibility_status",
                ):
                    self.assertIn(column, sql)
                self.assertNotIn("risk_tier", sql)
                self.assertFalse(any(token in sql for token in ("credit_score", "decision_reason")))
                self.assertTrue(is_safe_query(sql))

    def test_sanitized_csv_reasons_keep_allowed_reasons_and_drop_score_clauses(self):
        rejected = get_sanitized_sample_records("Rejected")
        self.assertTrue(rejected)
        self.assertTrue(all(row["eligibility_status"] == "Rejected" for row in rejected))
        safe_reasons = [
            reason
            for row in rejected
            for reason in row["recorded_reasons"]
        ]
        self.assertTrue(any("blacklisted" in reason.lower() for reason in safe_reasons))
        self.assertTrue(any("bankruptcy" in reason.lower() for reason in safe_reasons))
        self.assertFalse(any("score" in reason.lower() for reason in safe_reasons))

    def test_named_applicant_rejection_reasons_are_sanitized(self):
        record = get_applicant_rejection_basis_record(
            "Why was APP-2026-1003 rejected for installments?"
        )
        self.assertEqual(record["full_name"], "Usman Farooq")
        self.assertEqual(record["eligibility_status"], "Rejected")
        reasons = record["recorded_reasons"]
        self.assertTrue(any("blacklisted" in reason.lower() for reason in reasons))
        self.assertTrue(any("bankruptcy" in reason.lower() for reason in reasons))
        self.assertFalse(any("score" in reason.lower() for reason in reasons))

    def test_top_five_csv_reasons_are_available_without_restricted_details(self):
        records = get_sanitized_sample_records(
            "Approved", limit=5, rank_by_income=True
        )
        self.assertEqual(len(records), 5)
        self.assertTrue(all(row["eligibility_status"] == "Approved" for row in records))
        self.assertTrue(all(row["risk_tier"] == "A" for row in records))
        reasons = [reason for row in records for reason in row["recorded_reasons"]]
        self.assertTrue(any("affordability" in reason.lower() for reason in reasons))
        self.assertFalse(any("score" in reason.lower() for reason in reasons))

    def test_top_eligible_records_include_conditional_status_and_exclude_bankruptcy(self):
        question = (
            "top 5 person names that are eligible to take anything on installment"
        )
        self.assertTrue(pipeline.is_top_sample_eligibility_question(question))
        records = get_top_eligible_sample_records(question)
        self.assertEqual(len(records), 5)
        self.assertEqual(
            [record["full_name"] for record in records],
            [
                "Hina Hashmi",
                "Bushra Farooq",
                "Amna Warraich",
                "Nabeel Aslam",
                "Warda Tariq",
            ],
        )
        self.assertTrue(
            all(
                record["eligibility_status"]
                in ("Approved", "Approved with Conditions")
                for record in records
            )
        )
        self.assertTrue(all(record["bankruptcy_flag"] == "No" for record in records))

    def test_bankruptcy_sample_records_are_all_stored_rejected(self):
        self.assertTrue(
            is_bankruptcy_eligibility_question(
                "agr person bankkrupt ho to kya wo installment py ly skta h"
            )
        )
        self.assertEqual(get_bankruptcy_eligibility_counts(), {"Rejected": 7})

    def test_common_rejected_applicant_questions_skip_llm_routing_and_rephrasing(self):
        question = (
            "jo 5 person koi chiz nhi ly skty installment pr onk names do "
            "or onki wjah b do"
        )
        record = {
            "full_name": "Usman Farooq",
            "city": "Lahore",
            "risk_tier": "E",
            "eligibility_status": "Rejected",
            "monthly_net_income_pkr": 0,
            "avg_monthly_balance_pkr": 0,
            "active_loans_count": 3,
            "late_payments_12m": 9,
            "bounced_cheques_12m": 2,
            "bureau_status": "Blacklisted",
            "bankruptcy_flag": "Yes",
            "recorded_reasons": [
                "Blacklisted in credit bureau records",
                "Credit score below policy floor",
            ],
        }
        with (
            patch("pipeline._is_conversation_message", return_value=True) as conversation,
            patch("pipeline.rephrase_question") as rephrase,
            patch("pipeline.classify_question") as classify,
            patch("pipeline.run_query", return_value=(["sample_records"], [(1,)])),
            patch(
                "pipeline.get_sanitized_sample_records",
                return_value=[record],
            ) as get_records,
            patch("pipeline._final_answer", return_value="sample answer") as final_answer,
        ):
            result = pipeline.run_pipeline(question)

        self.assertEqual(result["route"], "sql")
        self.assertIn("Usman Farooq", result["answer"])
        self.assertIn("Net income: PKR 0", result["answer"])
        self.assertIn("Active loans: 3", result["answer"])
        self.assertIn("Blacklisted: Yes", result["answer"])
        self.assertIn("Bankruptcy: Yes", result["answer"])
        self.assertIn("Stored status: Rejected", result["answer"])
        self.assertIn(
            "Recorded reason(s): Blacklisted in credit bureau records",
            result["answer"],
        )
        self.assertNotIn("City", result["answer"])
        self.assertNotIn("Risk Tier", result["answer"])
        self.assertNotIn("score", result["answer"].lower())
        conversation.assert_not_called()
        rephrase.assert_not_called()
        classify.assert_not_called()
        get_records.assert_called_once_with("Rejected", limit=5)
        final_answer.assert_not_called()

    def test_generic_rejection_basis_reports_only_allowed_sample_factors(self):
        question = "Why are applicants rejected for installments?"
        record = {
            "eligibility_status": "Rejected",
            "monthly_gross_income_pkr": 0,
            "monthly_net_income_pkr": 0,
            "avg_monthly_balance_pkr": 30000,
            "active_loans_count": 3,
            "total_outstanding_debt_pkr": 50000,
            "monthly_debt_obligation_pkr": 15000,
            "late_payments_12m": 9,
            "bounced_cheques_12m": 3,
            "bureau_status": "Blacklisted",
            "bankruptcy_flag": "Yes",
            "recorded_reasons": [
                "Net monthly income below PKR 30,000 floor",
                "Blacklisted in credit bureau records",
                "Undischarged bankruptcy on file",
                "90+ days past due within last 24 months",
                "Repeat default on prior installment plans",
                "Three or more returned cheques in last 12 months",
                "Affordability failed - required installment exceeds available headroom",
                "Credit score below policy floor",
            ],
        }
        with (
            patch("pipeline.get_sanitized_sample_records", return_value=[record]) as get_records,
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(question)

        self.assertEqual(result["route"], "sql")
        for factor in (
            "income is zero or below PKR 30,000",
            "blacklisted status or bankruptcy=yes",
            "3 or more bounced cheques",
            "3-4 active loans",
            "required monthly installment exceeds",
            "stored decision_reason",
        ):
            self.assertIn(factor.lower(), result["answer"].lower())
        self.assertNotIn("to PKR", result["answer"])
        self.assertNotIn("CSV does not define", result["answer"])
        self.assertNotIn("risk tier", result["answer"].lower())
        self.assertNotIn("score", result["answer"].lower())
        get_records.assert_called_once_with("Rejected")
        final_answer.assert_not_called()

    def test_bankruptcy_question_uses_csv_counts_and_configured_rule(self):
        question = "agr person bankkrupt ho to kya wo koi chiz installment py ly skta h"
        with (
            patch(
                "pipeline.get_bankruptcy_eligibility_counts",
                return_value={"Rejected": 7},
            ) as get_counts,
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(question)

        self.assertEqual(result["route"], "sql")
        self.assertIn("income kitni bhi ho", result["answer"])
        self.assertIn("Stored status Rejected: 7", result["answer"])
        self.assertIn("Stored status Approved: 0", result["answer"])
        self.assertNotIn("risk tier", result["answer"].lower())
        self.assertNotIn("score", result["answer"].lower())
        get_counts.assert_called_once_with()
        final_answer.assert_not_called()

    def test_applicant_rejection_basis_uses_only_requested_fields(self):
        question = "Why was APP-2026-1003 rejected for installments?"
        record = {
            "applicant_id": "APP-2026-1003",
            "full_name": "Usman Farooq",
            "monthly_gross_income_pkr": 100000,
            "monthly_net_income_pkr": 0,
            "avg_monthly_balance_pkr": 30000,
            "active_loans_count": 3,
            "total_outstanding_debt_pkr": 50000,
            "monthly_debt_obligation_pkr": 0,
            "late_payments_12m": 9,
            "bounced_cheques_12m": 2,
            "previous_installment_defaults": 2,
            "bureau_status": "Blacklisted",
            "bankruptcy_flag": "Yes",
            "eligibility_status": "Rejected",
            "recorded_reasons": [
                "Blacklisted in credit bureau records",
                "Undischarged bankruptcy on file",
                "90+ days past due within last 24 months",
                "Net monthly income below PKR 30,000 floor",
                "Repeat default on prior installment plans",
                "Credit score below policy floor of 520",
            ],
        }
        with (
            patch("pipeline.get_applicant_rejection_basis_record", return_value=record),
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(question)

        self.assertEqual(result["route"], "sql")
        self.assertIn("Usman Farooq", result["answer"])
        self.assertIn("Stored status: Rejected", result["answer"])
        self.assertIn("PKR 30,000", result["answer"])
        self.assertIn("Blacklisted=Yes", result["answer"])
        self.assertIn("Bankruptcy=Yes", result["answer"])
        self.assertIn("90+ days past due", result["answer"])
        self.assertNotIn("risk tier", result["answer"].lower())
        self.assertNotIn("score", result["answer"].lower())
        final_answer.assert_not_called()

    def test_natural_top_five_question_skips_llm_rephrasing_and_routing(self):
        question = (
            "top 5 person names that are eligible to take anything on installment "
            "and tell me why they are eligible"
        )
        records = [
            {
                "full_name": "Conditional Applicant",
                "monthly_net_income_pkr": 100000,
                "avg_monthly_balance_pkr": 50000,
                "active_loans_count": 1,
                "late_payments_12m": 0,
                "bounced_cheques_12m": 0,
                "bureau_status": "Clear",
                "bankruptcy_flag": "No",
                "eligibility_status": "Approved with Conditions",
            }
        ]
        with (
            patch("pipeline._is_conversation_message", return_value=True) as conversation,
            patch("pipeline.rephrase_question") as rephrase,
            patch("pipeline.classify_question") as classify,
            patch("pipeline.get_top_eligible_sample_records", return_value=records) as get_records,
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(question)

        self.assertEqual(result["route"], "sql")
        self.assertIn("Approved with Conditions", result["answer"])
        self.assertIn("bankruptcy: No", result["answer"])
        self.assertNotIn("Risk Tier", result["answer"])
        self.assertIn("Conditional Applicant", result["answer"])
        get_records.assert_called_once_with(question)
        conversation.assert_not_called()
        rephrase.assert_not_called()
        classify.assert_not_called()
        final_answer.assert_not_called()

    def test_top_five_basis_followup_returns_allowed_status_and_factors(self):
        history = [
            {
                "role": "user",
                "content": "top 5 person that are eligible to take anything on installment",
            },
            {"role": "assistant", "content": "Here are five sample applicants."},
        ]
        record = {
            "full_name": "Sample Person",
            "eligibility_status": "Approved",
            "monthly_net_income_pkr": 90000,
            "avg_monthly_balance_pkr": 50000,
            "active_loans_count": 1,
            "late_payments_12m": 0,
            "bounced_cheques_12m": 0,
            "bureau_status": "Clear",
            "bankruptcy_flag": "No",
        }
        questions = (
            "on what basis you decide this",
            "why did you choose these people",
            "what factors did you consider for them",
            "how did you select them",
            "what is common between them",
            "in logon ko kis bunyaad par select kiya",
        )
        for question in questions:
            with (
                self.subTest(question=question),
                patch("pipeline._is_conversation_message", return_value=True) as conversation,
                patch("pipeline.rephrase_question") as rephrase,
                patch("pipeline.classify_question") as classify,
                patch("pipeline.run_query") as run_query,
                patch(
                    "pipeline.get_top_eligible_sample_records",
                    return_value=[record],
                ) as get_records,
                patch("pipeline._final_answer") as final_answer,
            ):
                result = pipeline.run_pipeline(question, history)

            self.assertEqual(result["route"], "sql")
            self.assertIn("income cutoff", result["answer"].lower())
            for field_value in (
                "net income",
                "bank balance",
                "active loans",
                "late payments",
                "bounced cheques",
                "blacklist",
                "bankruptcy",
                "stored status",
            ):
                self.assertIn(field_value, result["answer"].lower())
            self.assertNotIn("score", result["answer"].lower())
            self.assertNotIn("risk tier", result["answer"].lower())
            self.assertIn("Sample Person", result["answer"])
            if "bunyaad" in question:
                self.assertTrue(result["answer"].startswith("Yeh sample applications"))
            conversation.assert_not_called()
            rephrase.assert_not_called()
            classify.assert_not_called()
            run_query.assert_not_called()
            get_records.assert_called_once_with(history[0]["content"])
            final_answer.assert_not_called()

    def test_sql_cannot_read_excluded_fields_or_all_applicant_columns(self):
        self.assertIsNone(RESTRICTED_COLUMNS.search(SYSTEM_PROMPT))
        blocked_queries = (
            "SELECT credit_score FROM applicants",
            "SELECT decision_reason FROM applicants",
            "SELECT * FROM applicants",
            "SELECT applicants.* FROM applicants",
        )
        for sql in blocked_queries:
            with self.subTest(sql=sql):
                self.assertFalse(is_safe_query(sql))

        with (
            patch("text2sql_module.text_to_sql", return_value="SELECT credit_score FROM applicants"),
            patch("text2sql_module._execute") as execute,
        ):
            columns, rows = run_query("Show a restricted field for APP-2026-1003")

        self.assertEqual(columns, ["note"])
        self.assertEqual(rows, [])
        execute.assert_not_called()

    def test_final_prompt_does_not_expose_restricted_fields(self):
        self.assertIsNone(
            RESTRICTED_COLUMNS.search(pipeline.FINAL_SYSTEM_PROMPT)
        )

    def test_final_prompt_does_not_treat_zero_dti_as_favorable_without_income(self):
        self.assertIn(
            "do not describe a low or zero DTI as healthy, low debt, or a favorable factor",
            pipeline.FINAL_SYSTEM_PROMPT,
        )
        self.assertIn(
            "stored ratio cannot be meaningfully interpreted from this record",
            pipeline.FINAL_SYSTEM_PROMPT,
        )

    def test_top_sample_eligibility_list_uses_recorded_approvals_and_blacklist_filter(self):
        questions = (
            "Give me the top 5 names that are eligible to take any product on installment",
            "top 5 person that are eligible to take anything on installment",
            "top 5 person names that are eligible to take anything on installment and tell me why they are eligible",
        )
        for question in questions:
            with self.subTest(question=question):
                sql = text_to_sql(question)

                self.assertIn(
                    "eligibility_status IN ('Approved', 'Approved with Conditions')",
                    sql,
                )
                self.assertIn("LOWER(TRIM(bankruptcy_flag)) = 'no'", sql)
                self.assertIn("LOWER(TRIM(bureau_status)) != 'blacklisted'", sql)
                self.assertIn("ORDER BY monthly_net_income_pkr DESC", sql)
                self.assertIn("LIMIT 5", sql)
                self.assertNotIn("risk_tier", sql)
                self.assertNotIn("decision_reason", sql)
                self.assertNotIn("requested_appliance_category", sql)
                self.assertNotIn("appliance_categories", sql)

    def test_factor_eligibility_queries_use_aggregate_sample_outcomes_without_product_fields(self):
        cases = {
            "If a person is blacklisted, can he take anything on installment?":
                "LOWER(bureau_status) = 'blacklisted'",
            "If a person has no income source, can he take anything on installment?":
                "LOWER(employment_type) = 'unemployed'",
            "If someone has never paid any installment before, can they get installments?":
                "COALESCE(previous_installment_plans, 0) = 0",
        }
        for question, condition in cases.items():
            with self.subTest(question=question):
                sql = text_to_sql(question)
                self.assertIn("COUNT(*) AS sample_records", sql)
                self.assertIn(condition, sql)
                self.assertNotIn("requested_appliance_category", sql)
                self.assertNotIn("appliance_categories", sql)

    def test_factor_eligibility_question_stays_sql_only(self):
        question = "If a person is blacklisted, can he take anything on installment?"
        sql_question, rag_question = pipeline._split_question(question)
        self.assertEqual(sql_question, question)
        self.assertEqual(rag_question, "")

    def test_final_prompt_limits_sample_approval_to_requested_appliance(self):
        self.assertIn(
            "never claim an applicant is approved for any product",
            pipeline.FINAL_SYSTEM_PROMPT,
        )
        self.assertIn("Do not invent a minimum salary", pipeline.FINAL_SYSTEM_PROMPT)

    def test_top_sample_eligibility_query_does_not_read_product_fields(self):
        sql_question, rag_question = pipeline._split_question(
            "Give me the top 5 names that are eligible to take any product on installment"
        )

        self.assertIn("sample applicants", sql_question)
        self.assertIn("bureau status", sql_question)
        self.assertEqual(rag_question, "")

    def test_top_sample_eligibility_question_queries_sql_without_product_retrieval(self):
        question = "Give me the top 5 names that are eligible to take any product on installment"
        records = [
            {
                "full_name": "Sample Person",
                "monthly_net_income_pkr": 100000,
                "avg_monthly_balance_pkr": 50000,
                "active_loans_count": 0,
                "late_payments_12m": 0,
                "bounced_cheques_12m": 0,
                "bureau_status": "Clear",
                "bankruptcy_flag": "No",
                "eligibility_status": "Approved",
            }
        ]
        with (
            patch("pipeline._is_conversation_message", return_value=False),
            patch(
                "pipeline.rephrase_question",
                return_value=question,
            ),
            patch("pipeline.classify_question", return_value="sql"),
            patch("pipeline.get_top_eligible_sample_records", return_value=records) as get_records,
            patch("pipeline.run_query") as run_query,
            patch("pipeline.retrieve_context") as retrieve_context,
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(
                "Give me the top 5 names that are eligible to take any product on installment"
            )

        self.assertEqual(result["route"], "sql")
        get_records.assert_called_once_with(question)
        run_query.assert_not_called()
        retrieve_context.assert_not_called()
        self.assertEqual(result["rag_context"], "(not used for this question)")
        final_answer.assert_not_called()

    def test_final_prompt_uses_exact_loaded_product_catalog_count(self):
        self.assertGreater(pipeline.PRODUCT_CATALOG_COUNT, 0)
        self.assertIn(
            f"contains exactly {pipeline.PRODUCT_CATALOG_COUNT} product listings",
            pipeline.FINAL_SYSTEM_PROMPT,
        )
        self.assertIn("do not round it down to 240", pipeline.FINAL_SYSTEM_PROMPT)

    @patch("pipeline._final_answer", return_value="answer")
    @patch("pipeline.retrieve_context", return_value="Relevant policy details")
    @patch("pipeline.run_query", return_value=(["note"], []))
    @patch("pipeline.classify_question", return_value="sql")
    @patch("pipeline.rephrase_question", return_value="What is the refund policy?")
    @patch("pipeline._is_conversation_message", return_value=False)
    def test_sql_not_in_database_falls_back_to_rag(
        self,
        _is_conversation_message,
        _rephrase_question,
        _classify_question,
        _run_query,
        _retrieve_context,
        final_answer,
    ):
        result = pipeline.run_pipeline("What is the refund policy?")

        self.assertEqual(result["sql_results"], "NOT_IN_DATABASE")
        self.assertEqual(result["rag_context"], "Relevant policy details")
        final_answer.assert_called_once()
        self.assertEqual(final_answer.call_args.args[3], "NOT_IN_DATABASE")
        self.assertEqual(final_answer.call_args.args[4], "Relevant policy details")

    def test_public_eligibility_question_without_verified_context_returns_team_handoff(self):
        with (
            patch("pipeline._is_conversation_message", return_value=False),
            patch("pipeline.rephrase_question", return_value="Does Qistwalay guarantee approval?"),
            patch("pipeline.classify_question", return_value="rag"),
            patch("pipeline.retrieve_context", return_value=""),
            patch("pipeline._final_answer") as final_answer,
        ):
            result = pipeline.run_pipeline(
                "Does Qistwalay guarantee approval?"
            )

        self.assertEqual(result["route"], "rag")
        self.assertEqual(result["rag_context"], pipeline.RAG_INFORMATION_UNAVAILABLE)
        self.assertIn("Qistwalay team", result["answer"])
        final_answer.assert_not_called()

    def test_both_route_uses_sql_and_website_context(self):
        with (
            patch("pipeline._is_conversation_message", return_value=False),
            patch(
                "pipeline.rephrase_question",
                return_value="What is the recorded status for APP-2026-1003, and what does the website say about bankruptcy?",
            ),
            patch("pipeline.classify_question", return_value="both"),
            patch(
                "pipeline._split_question",
                return_value=(
                    "What is the recorded status and bankruptcy flag for APP-2026-1003?",
                    "Does Qistwalay's website specify how bankruptcy affects installment approval?",
                ),
            ),
            patch("pipeline.run_query", return_value=(["eligibility_status"], [("Rejected",)])) as run_query,
            patch("pipeline.retrieve_context", return_value="Website approval policy") as retrieve_context,
            patch("pipeline._final_answer", return_value="Combined answer") as final_answer,
        ):
            result = pipeline.run_pipeline(
                "What is applicant APP-2026-1003's status, and what is Qistwalay's bankruptcy policy?"
            )

        self.assertEqual(result["route"], "both")
        run_query.assert_called_once()
        retrieve_context.assert_called_once()
        self.assertEqual(result["sql_results"].splitlines()[-1], "Rejected")
        self.assertEqual(result["rag_context"], "Website approval policy")
        self.assertEqual(result["answer"], "Combined answer")
        final_answer.assert_called_once()

    def test_sql_route_does_not_query_website_context(self):
        with (
            patch("pipeline._is_conversation_message", return_value=False),
            patch(
                "pipeline.rephrase_question",
                return_value="What is the recorded risk tier for APP-2026-1003?",
            ),
            patch("pipeline.classify_question", return_value="sql"),
            patch("pipeline.run_query", return_value=(["risk_tier"], [("E",)])),
            patch("pipeline.retrieve_context") as retrieve_context,
            patch("pipeline._final_answer", return_value="Sample risk tier E."),
        ):
            result = pipeline.run_pipeline(
                "What is the recorded risk tier for APP-2026-1003?"
            )

        self.assertEqual(result["route"], "sql")
        self.assertIn("E", result["sql_results"])
        self.assertEqual(result["rag_context"], "(not used for this question)")
        retrieve_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
