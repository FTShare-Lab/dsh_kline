"""Host guidance contracts, not proof of model compliance or expert pattern quality."""
import asyncio
import unittest

import server


class DrawingIntentContractTests(unittest.TestCase):
    def test_analysis_authorization_is_distinct_from_literal_coordinates(self):
        instructions = server.mcp.instructions
        self.assertIn("literal drawing from analysis-assisted drawing", instructions)
        self.assertIn("YOU, the host, may derive a candidate", instructions)
        self.assertIn("the plugin does not choose anchors or assess pattern quality", instructions)
        self.assertIn("do not prepare, queue or mutate drawings before", instructions)
        self.assertIn("their confirmation", instructions)
        self.assertNotIn("without explicit user anchors", instructions)

    def test_view_transition_does_not_authorize_refetch_or_stale_edit(self):
        instructions = server.mcp.instructions
        self.assertIn("NOT a reason to call fetch_candles or analyze_kline again", instructions)
        self.assertIn("newly injected current-view reference", instructions)
        self.assertIn("reassess and seek confirmation", instructions)
        self.assertIn("using the observed revision and aligned source", instructions)
        self.assertIn("Unknown results must not be automatically", instructions)

    def test_verification_is_based_on_approved_expectations_not_mutation_output(self):
        instructions = server.mcp.instructions
        self.assertIn("user-approved proposal and overrides", instructions)
        self.assertIn("expectations independently of the execution result", instructions)
        self.assertIn("NOT fields copied from the mutation result", instructions)
        self.assertIn("not screen pixels", instructions)

    def test_numeric_claims_and_reply_style_are_conservative(self):
        instructions = server.mcp.instructions
        self.assertIn("when an intervening bar increases", instructions)
        self.assertIn("subjective candidate as uniquely correct", instructions)
        self.assertIn("do not force a platform", instructions)
        self.assertIn("omit internal IDs", instructions)

    def test_intersection_guidance_does_not_claim_union_coverage(self):
        # Contract visibility only; a real host retest is still required.
        context = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "get_chart_context")
        for guidance in (server.mcp.instructions, context.description):
            self.assertIn("EVERY body", guidance)
            self.assertIn("does NOT imply a gap uncovered by ANY body", guidance)
            self.assertIn("difference is not an uncovered gap", guidance)
            self.assertIn("union coverage is not measured", guidance)

    def test_tool_schema_still_requires_explicit_geometry_and_readonly_verification(self):
        tools = asyncio.run(server.mcp.list_tools())
        rectangle = next(t for t in tools if t.name == "create_rectangle")
        self.assertTrue({"start_time", "end_time", "lower_price", "upper_price"} <= set(rectangle.inputSchema["required"]))
        self.assertIn("用户确认", rectangle.inputSchema["properties"]["lower_price"]["description"])
        self.assertTrue(next(t.annotations.readOnlyHint for t in tools if t.name == "verify_chart_drawings"))
        self.assertIn("executor does no pattern recognition", rectangle.description)
        context = next(t for t in tools if t.name == "get_chart_context")
        self.assertIn("HOST may choose a candidate", context.description)
        self.assertIn("region_start_time/region_end_time", context.description)
        self.assertIn("NOT another market fetch", context.description)
        self.assertIn("boundary_evidence", context.description)
        self.assertIn("lower>upper is EMPTY", context.description)
        self.assertIn("Never turn exists=false/relation=empty", context.description)
        self.assertIn("AFTER the user approves", next(t for t in tools if t.name == "prepare_chart_edit").description)


if __name__ == "__main__":
    unittest.main()
