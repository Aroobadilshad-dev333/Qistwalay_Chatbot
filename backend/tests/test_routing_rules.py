import sys
import unittest
from unittest.mock import patch

import numpy as np

import pipeline
import router

chatbot_agent = sys.modules[pipeline.retrieve_context.__module__]


class RoutingRulesTests(unittest.TestCase):
    def test_natural_roman_urdu_rejected_applicant_list_routes_to_sql(self):
        questions = [
            "aaisy person jo nhi ly skty installment pr chiz onka name btao",
            "Jo 5 person koi cheez installment par nahi le sakte",
            "Kon nahi le sakta aur kyun installment par?",
            "Tell me the names of people who can't get installments.",
        ]
        for question in questions:
            with self.subTest(question=question), patch.object(
                router.client.chat.completions, "create"
            ) as create:
                self.assertEqual(router.classify_question(question), "sql")
                create.assert_not_called()

    def test_natural_rejection_basis_question_routes_to_sql(self):
        questions = [
            "or kis basis pr tm decide krty ho koi person installment pr chiz nhi ly skta",
            "On what basis are installment applications rejected?",
        ]
        for question in questions:
            with self.subTest(question=question), patch.object(
                router.client.chat.completions, "create"
            ) as create:
                self.assertEqual(router.classify_question(question), "sql")
                create.assert_not_called()

    def test_excluded_field_questions_route_to_sql_without_model_call(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "What is the recorded credit score for applicant APP-2026-1003?"
            )

        self.assertEqual(route, "sql")
        create.assert_not_called()

    def test_general_qistwalay_questions_route_to_rag_without_model_call(self):
        questions = [
            "Tell me about Qistwalay",
            "Qistwalay k bary my ap kya janty h",
        ]
        for question in questions:
            with self.subTest(question=question), patch.object(
                router.client.chat.completions, "create"
            ) as create:
                self.assertEqual(router.classify_question(question), "rag")
                create.assert_not_called()

    def test_general_bankruptcy_question_routes_to_rag_without_model_call(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "if the person is bankrupt can he take installment"
            )

        self.assertEqual(route, "rag")
        create.assert_not_called()

    def test_applicant_installment_decision_uses_both_sources(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "Can applicant APP-2026-1003 get a product on installments?"
            )

        self.assertEqual(route, "both")
        create.assert_not_called()

    def test_applicant_bankruptcy_record_uses_sql_only(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question("Is APP-2026-1003 marked bankrupt?")

        self.assertEqual(route, "sql")
        create.assert_not_called()

    def test_named_applicant_eligibility_uses_both_sources(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "Can Yasir Chaudhry get a product on installments?"
            )

        self.assertEqual(route, "both")
        create.assert_not_called()

    def test_personal_eligibility_question_routes_to_rag(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "I earn 80000; can I get a refrigerator on installments?"
            )

        self.assertEqual(route, "rag")
        create.assert_not_called()

    def test_top_sample_eligibility_list_routes_to_sql_without_model_call(self):
        questions = [
            "Give me the top 5 names that are eligible to take any product on installment",
            "top 5 person that are eligible to take anything on installment",
        ]
        for question in questions:
            with self.subTest(question=question), patch.object(
                router.client.chat.completions, "create"
            ) as create:
                self.assertEqual(router.classify_question(question), "sql")
                create.assert_not_called()

    def test_factor_based_hypothetical_eligibility_questions_use_sample_sql(self):
        questions = [
            "If a person is blacklisted, can he take anything on installment?",
            "If a person has no income source, can he take anything on installment?",
            "If a person has never paid any installment before, can they get a product on installments?",
        ]
        for question in questions:
            with self.subTest(question=question), patch.object(
                router.client.chat.completions, "create"
            ) as create:
                self.assertEqual(router.classify_question(question), "sql")
                create.assert_not_called()

    def test_product_price_question_remains_rag_only(self):
        with patch.object(router.client.chat.completions, "create") as create:
            create.return_value.choices[0].message.content = "rag"
            route = router.classify_question("What is the price of this product?")

        self.assertEqual(route, "rag")
        create.assert_called_once()

    def test_applicant_id_lookup_routes_to_sql_without_model_call(self):
        with patch.object(router.client.chat.completions, "create") as create:
            route = router.classify_question(
                "What is the recorded risk tier for applicant APP-2026-1003?"
            )

        self.assertEqual(route, "sql")
        create.assert_not_called()


class RetrievalGroundingTests(unittest.TestCase):
    def test_general_qistwalay_questions_return_homepage_overview_without_embedding(self):
        overview_chunks = [
            {
                "type": "homepage_info",
                "metadata": {"section": "about_blurb"},
                "text": "Qistwalay sells electronics and appliances in Lahore.",
            },
            {
                "type": "homepage_info",
                "metadata": {"section": "deal_packs"},
                "text": "Qistwalay offers Jahez and Room bundle packages.",
            },
            {
                "type": "product_overview",
                "metadata": {},
                "text": "A specific refrigerator product.",
            },
        ]
        with (
            patch.object(chatbot_agent, "chunks", overview_chunks),
            patch.object(chatbot_agent, "index", object()),
            patch.object(chatbot_agent, "get_query_embedding") as get_embedding,
        ):
            for question in (
                "Tell me about Qistwalay",
                "Qistwalay k bary my ap kya janty h",
            ):
                with self.subTest(question=question):
                    context = chatbot_agent.retrieve_context(question)
                    self.assertIn("electronics and appliances in Lahore", context)
                    self.assertIn("Jahez and Room bundle packages", context)
                    self.assertNotIn("A specific refrigerator", context)

            get_embedding.assert_not_called()

    def test_unmatched_bankruptcy_term_returns_no_context(self):
        class FakeIndex:
            def search(self, query, candidates):
                self.query = query
                self.candidates = candidates
                return np.array([[0.1, 0.2]], dtype="float32"), np.array([[0, 1]])

        fake_index = FakeIndex()
        with (
            patch.object(chatbot_agent, "index", fake_index),
            patch.object(
                chatbot_agent,
                "chunks",
                [
                    {"text": "Installment plans are available for selected products."},
                    {"text": "Customers may submit an installment plan application."},
                ],
            ),
            patch.object(
                chatbot_agent,
                "get_query_embedding",
                return_value=np.array([[1.0, 0.0]], dtype="float32"),
            ),
        ):
            context = chatbot_agent.retrieve_context(
                "if the person is bankrupt can he take installment"
            )

        self.assertEqual(context, "")
        self.assertEqual(fake_index.candidates, 30)

    def test_matching_policy_terms_are_returned(self):
        class FakeIndex:
            def search(self, query, candidates):
                self.query = query
                self.candidates = candidates
                return np.array([[0.1]], dtype="float32"), np.array([[0]])

        fake_index = FakeIndex()
        with (
            patch.object(chatbot_agent, "index", fake_index),
            patch.object(
                chatbot_agent,
                "chunks",
                [{"text": "Required customer documents for an installment purchase."}],
            ),
            patch.object(
                chatbot_agent,
                "get_query_embedding",
                return_value=np.array([[1.0, 0.0]], dtype="float32"),
            ),
        ):
            context = chatbot_agent.retrieve_context(
                "What documents are required for installment plans?"
            )

        self.assertIn("Required customer documents", context)
        self.assertEqual(fake_index.candidates, 30)


if __name__ == "__main__":
    unittest.main()
