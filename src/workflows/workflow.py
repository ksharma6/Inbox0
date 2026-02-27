import datetime
import json
import os
import uuid
from typing import Dict, List

from langgraph.graph import END, StateGraph
from openai import OpenAI
from src.gmail import GmailReader, GmailWriter
from src.models.agent import GmailAgentState
from src.models.gmail import EmailSummary
from src.slack_handlers.draft_approval_handler import DraftApprovalHandler

from .state_manager import save_state_to_store


class EmailProcessingWorkflow:
    """LangGraph workflow for processing/summarizing emails and generating draft responses to send to user via Slack.

    Please note that user must have api keys and paths for GMail credentials in .env file.

    Args:
        gmail_reader: GmailReader object
        gmail_writer: GmailWriter object
        draft_handler: DraftApprovalHandler object
        openai_client: OpenAI object

    Example:
        workflow = EmailProcessingWorkflow(
            gmail_reader=GmailReader(),
            gmail_writer=GmailWriter(),
            draft_handler=DraftApprovalHandler(),
            openai_client=OpenAI(),
        )
        workflow.run()
    """

    def __init__(
        self,
        gmail_reader: GmailReader,
        gmail_writer: GmailWriter,
        draft_handler: DraftApprovalHandler,
        openai_client: OpenAI,
    ):
        self.gmail_reader = gmail_reader
        self.gmail_writer = gmail_writer
        self.draft_handler = draft_handler
        self.openai_client = openai_client

        self.workflow = self._create_workflow()

    def _create_workflow(self):
        """Create and return the compiled LangGraph workflow

        The workflow is a state machine that processes emails and generates draft responses using the following nodes:
        - read_unread_emails: reads last 5 unread emails from user's Gmail account using GmailReader
        - generate_email_summary: generates a high-level summary of unread emails using OpenAI
        - process_emails_for_drafts: analyzes emails and determines which need draft responses using OpenAI
        - create_draft_responses: creates draft responses for emails that need them using OpenAI
        - send_drafts_to_slack: sends draft responses to Slack for approval using DraftApprovalHandler
        - wait_for_user_action: waits for user action to continue the workflow

        Returns:
            workflow: compiled LangGraph workflow
        """
        workflow = StateGraph[GmailAgentState, None, GmailAgentState, GmailAgentState](
            GmailAgentState
        )

        workflow.add_node("read_unread_emails", self._read_unread_emails)
        workflow.add_node("generate_email_summary", self._generate_email_summary)
        workflow.add_node("process_emails_for_drafts", self._process_emails_for_drafts)
        workflow.add_node("create_draft_responses", self._create_draft_responses)
        workflow.add_node("send_drafts_to_slack", self._send_drafts_to_slack)
        workflow.add_node("wait_for_user_action", self._wait_for_user_action)
        workflow.add_node("send_final_summary", self._send_final_summary)

        workflow.set_entry_point("read_unread_emails")

        workflow.add_edge("read_unread_emails", "generate_email_summary")
        workflow.add_edge("generate_email_summary", "process_emails_for_drafts")
        workflow.add_edge("process_emails_for_drafts", "create_draft_responses")
        workflow.add_edge("create_draft_responses", "send_drafts_to_slack")

        # conditional edges - user input required for approval
        workflow.add_conditional_edges(
            "send_drafts_to_slack",
            lambda state: state.current_draft_index >= len(state.draft_responses),
            {
                True: "send_final_summary",
                False: "wait_for_user_action",
            },
        )

        workflow.add_conditional_edges(
            "wait_for_user_action",
            lambda state: state.awaiting_approval == False,
            {
                True: "send_drafts_to_slack",
                False: "wait_for_user_action",  # Loop back to wait
            },
        )

        workflow.add_edge("send_final_summary", END)

        return workflow.compile()

    def _read_unread_emails(self, state: GmailAgentState) -> GmailAgentState:
        """Read last 5 unread emails from user's Gmail account

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object with unread_emails list
        """
        unread_emails = self.gmail_reader.read_emails(
            count=5, unread_only=True, include_body=True, primary_only=True
        )
        # for each email thread, get only the 4 most recent emails
        recent_emails = []
        for email in unread_emails:
            thread_emails = self.gmail_reader.get_recent_emails_in_thread(
                email.thread_id, count=4
            )
            recent_emails.extend(thread_emails)

        state.unread_emails = list({e.id: e for e in recent_emails}.values())
        return state

    def _generate_email_summary(self, state: GmailAgentState) -> GmailAgentState:
        """Generate a high-level summary of unread emails using OpenAI

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object with email_summary object
        """
        try:
            if not state.unread_emails:
                state.email_summary = None
                return state

            print("Generating email summary...")

            # Create summary using OpenAI and summarizing only 3 emails
            emails_text = self._format_emails_for_summary(state.unread_emails[:3])

            prompt = f"""
            You are an email assistant. Please provide a high-level summary of the following unread emails.
            Focus on:
            1. Key themes and topics
            2. Urgent or important emails
            3. Action items required
            4. Senders who need responses
            
            Emails:
            {emails_text}
            
            Provide a concise, professional summary:
            """

            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            summary_text = response.choices[0].message.content

            state.email_summary = EmailSummary(
                total_unread=len(state.unread_emails),
                emails=state.unread_emails,
                summary_by_sender=self._group_by_sender(state.unread_emails),
                urgent_emails=[e for e in state.unread_emails if e.is_important],
                recent_activity=summary_text or "No summary available",
            )

            print("Email summary generated successfully")

        except Exception as e:
            state.error_message = f"Error generating summary: {str(e)}"
            state.should_continue = False

        return state

    def _process_emails_for_drafts(self, state: GmailAgentState) -> GmailAgentState:
        """Analyze emails and determine which need draft responses using OpenAI

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object with processed_emails list
        """
        try:
            if not state.unread_emails:
                return state

            print("Processing emails for draft responses...")

            emails_text = self._format_emails_for_analysis(state.unread_emails)

            prompt = f"""
            Analyze these emails and determine which ones need draft responses.
            Consider:
            1. Is this a personal email that requires a response?
            2. Is this from someone important (boss, client, colleague)?
            3. Does the email ask a question or require action?
            4. Is this spam or promotional content (don't respond)?
            
            For each email that needs a response, provide:
            - Email ID: {state.unread_emails[0].id}
            - Priority: High/Medium/Low
            - Response type: Reply/Forward/New email
            - Brief reason why response is needed
            
            Emails:
            {emails_text}
            
            Respond in JSON format:
            {{
                "emails_to_respond": [
                    {{
                        "email_id": "id",
                        "priority": "High/Medium/Low",
                        "response_type": "Reply/Forward/New",
                        "reason": "brief reason"
                    }}
                ]
            }}
            """

            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )

            content = response.choices[0].message.content
            if content:
                analysis = json.loads(content)
            else:
                analysis = {"emails_to_respond": []}

            state.processed_emails = analysis.get("emails_to_respond", [])

            print(f"Identified {len(state.processed_emails)} emails needing responses")

        except Exception as e:
            state.error_message = f"Error processing emails: {str(e)}"
            state.should_continue = False

        return state

    def _create_draft_responses(self, state: GmailAgentState) -> GmailAgentState:
        """Create draft responses for emails that have been determined to need them using OpenAI

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object with draft_responses list
        """
        try:
            if not state.processed_emails:
                return state

            print("Creating draft responses...")

            draft_responses = []

            for email_info in state.processed_emails:
                email_id = email_info["email_id"]

                # Find the corresponding email
                email = next((e for e in state.unread_emails if e.id == email_id), None)
                if not email:
                    continue

                # Generate draft response using OpenAI
                draft_content = self._generate_draft_response(email, email_info)

                # Create draft using GmailWriter
                try:
                    draft = self.gmail_writer.create_draft(
                        sender=email.to_email,  # Reply to the sender
                        recipient=email.from_email,
                        subject=f"Re: {email.subject}",
                        message=draft_content,
                    )

                    draft_responses.append(
                        {
                            "email_id": email_id,
                            "draft": draft,
                            "priority": email_info["priority"],
                            "original_email": email,
                            "draft_content": draft_content,
                        }
                    )

                except Exception as e:
                    print(f"Error creating draft for email {email_id}: {e}")
                    continue

            state.draft_responses = draft_responses
            print(f"Created {len(draft_responses)} draft responses")

        except Exception as e:
            state.error_message = f"Error creating drafts: {str(e)}"
            state.should_continue = False

        return state

    def _send_drafts_to_slack(self, state: GmailAgentState) -> GmailAgentState:
        """Send draft responses to Slack for approval

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object with awaiting_approval and current_draft_index
        """
        TIMEOUT_SECONDS = 3600  # 1 hour

        if not state.draft_responses or state.current_draft_index >= len(
            state.draft_responses
        ):
            state.awaiting_approval = False
            return state

        if state.awaiting_approval:
            now = datetime.datetime.now()
            if (now - state.awaiting_approval_since).total_seconds() > TIMEOUT_SECONDS:
                state.awaiting_approval = False
                state.current_draft_index += 1
            return state

        draft_info = state.draft_responses[state.current_draft_index]

        draft_id = self.draft_handler.send_draft_for_approval(
            draft=draft_info["draft"],
            user_id=state.user_id,
        )

        if draft_id:
            state.current_draft_id = draft_id

        state.awaiting_approval = True
        state.awaiting_approval_since = datetime.datetime.now()
        save_state_to_store(state)
        return state

    def _wait_for_user_action(self, state: GmailAgentState) -> GmailAgentState:
        """Wait for user action to continue the workflow

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object
        """
        return state

    def _send_final_summary(self, state: GmailAgentState) -> GmailAgentState:
        """Send final summary to the user summarizing the workflow and any errors

        Args:
            state: GmailAgentState object

        Returns:
            GmailAgentState object
        """
        try:
            print("Sending final summary...")

            summary_parts = []

            if state.email_summary:
                summary_parts.append(
                    f"📧 *Email Summary*\n{state.email_summary.recent_activity}"
                )

            if state.draft_responses:
                summary_parts.append(
                    f"\n📝 *Draft Responses Created*\n{len(state.draft_responses)} draft responses have been created and sent to Slack for your approval."
                )

            if state.pending_approvals:
                summary_parts.append(
                    f"\n⏳ *Pending Approvals*\n{len(state.pending_approvals)} drafts are waiting for your approval in Slack."
                )

            if state.error_message:
                summary_parts.append(f"\n⚠️ *Errors*\n{state.error_message}")

            final_summary = (
                "\n".join(summary_parts) if summary_parts else "No emails processed."
            )

            try:
                target = state.user_id
                print(f"Final summary:\n{final_summary}")

            except Exception as e:
                print(f"Error sending final summary: {e}")

            state.final_summary = final_summary
            state.workflow_complete = True

        except Exception as e:
            state.error_message = f"Error sending final summary: {str(e)}"

        return state

    def _format_emails_for_summary(self, emails: List) -> str:
        """Format emails for summary generation

        Args:
            emails: list of Email objects

        Returns:
            formatted string of emails
        """
        formatted = []
        for i, email in enumerate(emails, 1):
            formatted.append(f"{i}. From: {email.from_email}")
            formatted.append(f"   Subject: {email.subject}")
            formatted.append(f"   Date: {email.date}")
            formatted.append(f"   Important: {email.is_important}")
            formatted.append(f"   Body: {email.body[:300]}...")
            formatted.append("")
        return "\n".join(formatted)

    def _format_emails_for_analysis(self, emails: List) -> str:
        """Format emails for analysis"""
        formatted = []
        for email in emails:
            formatted.append(f"ID: {email.id}")
            formatted.append(f"From: {email.from_email}")
            formatted.append(f"Subject: {email.subject}")
            formatted.append(f"Date: {email.date}")
            formatted.append(f"Important: {email.is_important}")
            formatted.append(f"Body: {email.body[:500]}")
            formatted.append("---")
        return "\n".join(formatted)

    def _group_by_sender(self, emails: List) -> Dict:
        """Group emails by sender

        Args:
            emails: list of Email objects

        Returns:
            dictionary of emails grouped by sender
        """
        groups = {}
        for email in emails:
            sender = email.from_email
            if sender not in groups:
                groups[sender] = []
            groups[sender].append(email)
        return groups

    def _generate_draft_response(self, email, email_info: Dict) -> str:
        """Generate draft response content using OpenAI

        Args:
            email: Email object
            email_info: dictionary of email information

        Returns:
            draft response content
        """
        salutation = os.getenv("EMAIL_SALUTATION")
        signature = os.getenv("EMAIL_SIGNOFF")

        truncated_body = email.body[:8000] if email.body else ""

        prompt = f"""
        You are a professional email assistant. Generate a draft response for this email.
        
        Original Email:
        From: {email.from_email}
        Subject: {email.subject}
        Body: {truncated_body}
        
        Response Requirements:
        - Priority: {email_info['priority']}
        - Response Type: {email_info['response_type']}
        - Reason: {email_info['reason']}
        
        Guidelines:
        1. Identify the sender's first name from the "From" field: "{email.from_email}"
        2. Use the salutation pattern: "{salutation}"
           - Replace "{{name}}" with the sender's actual name (e.g. "Hello John,").
           - If the name cannot be found, fallback to a generic friendly greeting like "Hello,".
        3. Be professional and courteous
        4. Address the key points from the original email
        5. Keep it succinct but complete. Avoid using too many words and flowery language.
        6. Match the tone of the original email
        7. Include a clear call to action if needed
        8. End the email with the signature: "{signature}"
        
        Generate the draft response:
        """

        response = self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )

        content = response.choices[0].message.content
        return content or "No response generated"

    def run(self, user_id: str) -> GmailAgentState:
        """Run the email processing workflow

        Args:
            user_id: string of user id

        Returns:
            GmailAgentState object
        """
        thread_id = str(uuid.uuid4())

        initial_state = GmailAgentState(
            user_id=user_id,
            thread_id=thread_id,
        )

        # run the workflow
        result_gen = self.workflow.stream(initial_state)

        for state in result_gen:
            final_state = state

        return final_state
