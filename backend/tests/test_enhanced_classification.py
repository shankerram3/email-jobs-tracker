"""
Test the enhanced classification pipeline with filtering and extraction.
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.email_relevance_filter import (
    is_job_related_email,
    rule_based_relevance_check,
    filter_job_emails,
)


class TestEmailRelevanceFilter:
    """Test the email relevance filter."""

    def test_obvious_non_job_email_openai_billing(self):
        """The OpenAI billing email should be filtered out."""
        subject = "Update your payment method to keep using Plus"
        body = """Update payment Please update your payment method to keep access to Plus benefits:
        - Extended limits on messaging, file uploads, and voice mode
        - More image and video generation
        - Extended access to deep research and reasoning models
        If you have any questions, we're here at support@openai.com.
        Best, The ChatGPT Team 3180 18th St San Francisco, CA 94110
        Terms Privacy openai.com"""
        sender = "noreply@openai.com"

        # Rule-based should catch this
        rule_result = rule_based_relevance_check(subject, body, sender)
        assert rule_result is False, "OpenAI billing email should be filtered by rules"

        # Full check should also filter
        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is False, f"OpenAI billing email should not be relevant: {reason}"
        assert confidence >= 0.7, "Should have high confidence it's not job-related"

    def test_job_application_email_passes(self):
        """Job application emails should pass the filter."""
        subject = "Thank you for applying to Google!"
        body = """Thank you for your interest in the Software Engineer position at Google.
        We have received your application and will review it shortly.
        If selected for an interview, a recruiter will reach out within two weeks."""
        sender = "jobs@google.com"

        rule_result = rule_based_relevance_check(subject, body, sender)
        assert rule_result is True or rule_result is None, "Job application should not be filtered by rules"

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is True, f"Job application should be relevant: {reason}"

    def test_recruiter_outreach_passes(self):
        """Recruiter outreach should pass the filter."""
        subject = "Exciting opportunity at Meta"
        body = """Hi, I came across your profile on LinkedIn and thought you'd be a great fit
        for our Senior Software Engineer role. Would you be interested in learning more?"""
        sender = "recruiter@meta.com"

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is True, f"Recruiter outreach should be relevant: {reason}"

    def test_interview_invite_passes(self):
        """Interview invitations should pass."""
        subject = "Interview invitation - Senior Backend Engineer"
        body = """We'd like to invite you for a technical interview for the Senior Backend
        Engineer position. Please let us know your availability."""
        sender = "talent@stripe.com"

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is True, f"Interview invite should be relevant: {reason}"

    def test_newsletter_filtered(self):
        """Newsletters should be filtered."""
        subject = "Weekly Tech Digest - Top Stories"
        body = """This week's top tech news: AI advances, new product launches...
        Click here to read more. Unsubscribe from this newsletter."""
        sender = "newsletter@techdigest.com"

        rule_result = rule_based_relevance_check(subject, body, sender)
        assert rule_result is False, "Newsletter should be filtered by rules"

    def test_password_reset_filtered(self):
        """Password reset emails should be filtered."""
        subject = "Reset your password"
        body = """We received a request to reset your password. Click the link below
        to set a new password. If you didn't request this, ignore this email."""
        sender = "noreply@spotify.com"

        rule_result = rule_based_relevance_check(subject, body, sender)
        assert rule_result is False, "Password reset should be filtered by rules"

    def test_order_confirmation_filtered(self):
        """Order confirmations should be filtered."""
        subject = "Your order has been confirmed"
        body = """Thank you for your purchase! Your order #12345 has been confirmed
        and will ship within 2 business days. Track your shipment here."""
        sender = "orders@amazon.com"

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is False, f"Order confirmation should not be relevant: {reason}"

    def test_ats_domain_always_relevant(self):
        """Emails from ATS domains should always be considered relevant."""
        subject = "Application Update"
        body = "Your application status has been updated."
        sender = "notifications@greenhouse.io"

        rule_result = rule_based_relevance_check(subject, body, sender)
        assert rule_result is True, "ATS domain emails should always pass"

    def test_coding_challenge_passes(self):
        """Coding challenge invites should pass."""
        subject = "Complete your HackerRank assessment"
        body = """You've been invited to complete a coding assessment for the
        Software Engineer position. The assessment consists of 3 problems."""
        sender = "no-reply@hackerrank.com"

        is_relevant, confidence, reason = is_job_related_email(subject, body, sender)
        assert is_relevant is True, f"Coding challenge should be relevant: {reason}"

    def test_filter_batch_function(self):
        """Test the batch filter function."""
        emails = [
            {
                "subject": "Thank you for applying!",
                "body": "We received your application for Software Engineer.",
                "sender": "jobs@company.com",
            },
            {
                "subject": "Update your payment method",
                "body": "Your subscription payment failed.",
                "sender": "billing@service.com",
            },
            {
                "subject": "Interview request",
                "body": "We'd like to schedule an interview.",
                "sender": "hr@startup.com",
            },
        ]

        # Note: This would need LLM in real usage, so we just test the interface
        # In real tests, you'd mock the LLM calls
        filtered = filter_job_emails(emails)
        assert isinstance(filtered, list)


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_enhanced_classification.py -v
    pytest.main([__file__, "-v"])
