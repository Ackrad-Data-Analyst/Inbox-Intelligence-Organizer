from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from inbox_organizer.classifier import SemanticClassifier
from inbox_organizer.engine import apply_operations, classify_messages
from inbox_organizer.models import Action, Category
from inbox_organizer.policy import plan_operation, recommended_action, validate_confirmation
from inbox_organizer.providers import GmailProvider, ImapProvider, MicrosoftProvider


ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / ".private"
AUDIT = ROOT / "audit" / "operations.jsonl"

st.set_page_config(page_title="Inbox Intelligence Organizer", page_icon="📬", layout="wide")
st.title("Inbox Intelligence Organizer")
st.caption("Semantic full-message triage with review-first, recoverable mailbox actions")


def connect_provider(kind: str):
    if kind == "Gmail":
        if not gmail_credentials:
            raise ValueError("Upload the Desktop OAuth credentials JSON from Google Cloud")
        PRIVATE.mkdir(exist_ok=True)
        credentials_path = PRIVATE / "gmail_credentials.json"
        credentials_path.write_bytes(gmail_credentials.getvalue())
        provider = GmailProvider(credentials_path, PRIVATE / "gmail_token.json")
    elif kind == "Microsoft Outlook / Microsoft 365":
        if not microsoft_client_id:
            raise ValueError("Enter the client ID from your Microsoft app registration")
        provider = MicrosoftProvider(microsoft_client_id, microsoft_tenant)
    else:
        if not imap_host or not imap_user or not imap_password:
            raise ValueError("Enter the IMAP host, account address, and app password")
        provider = ImapProvider(imap_host, imap_user, imap_password, int(imap_port))
    provider.connect()
    return provider


with st.sidebar:
    st.header("1 · Mailbox")
    provider_kind = st.selectbox("Provider", ["Gmail", "Microsoft Outlook / Microsoft 365", "Yahoo / Generic IMAP"])
    gmail_credentials = None
    microsoft_client_id = microsoft_tenant = ""
    imap_host = imap_user = imap_password = ""
    imap_port = 993
    if provider_kind == "Gmail":
        gmail_credentials = st.file_uploader("Google Desktop OAuth credentials.json", type=["json"])
        st.caption("The browser opens for OAuth consent. The app never reads browser cookies.")
    elif provider_kind == "Microsoft Outlook / Microsoft 365":
        microsoft_client_id = st.text_input("Microsoft application client ID")
        microsoft_tenant = st.text_input("Tenant", "common")
        st.caption("Interactive delegated OAuth requests Mail.ReadWrite.")
    else:
        preset = st.selectbox("Preset", ["Yahoo", "Other IMAP"])
        imap_host = st.text_input("IMAP host", "imap.mail.yahoo.com" if preset == "Yahoo" else "")
        imap_port = st.number_input("IMAP SSL port", 1, 65535, 993)
        imap_user = st.text_input("Email address")
        imap_password = st.text_input("App password (memory only)", type="password")
    if st.button("Connect mailbox", type="primary"):
        try:
            st.session_state.mail_provider = connect_provider(provider_kind)
            st.session_state.folders = st.session_state.mail_provider.list_folders()
            st.session_state.pop("classified", None)
            st.success("Connected")
        except Exception as exc:
            st.error(f"Connection failed: {exc}")

    st.header("2 · Semantic model")
    ai_provider = st.selectbox("Classifier", ["Local Ollama (recommended)", "OpenAI-compatible remote"])
    if ai_provider.startswith("Local"):
        ai_url = st.text_input("Ollama endpoint", "http://localhost:11434/api/chat")
        ai_model = st.text_input("Local model", "llama3.2:3b")
        ai_key = ""
        st.caption("Email content stays on this computer when Ollama runs locally.")
    else:
        st.warning("The selected provider receives message content. Confirm authorization and retention terms.")
        ai_url = st.text_input("Chat-completions endpoint", "https://api.openai.com/v1/chat/completions")
        ai_model = st.text_input("Model", "gpt-5-mini")
        ai_key = st.text_input("API key (memory only)", type="password")

provider = st.session_state.get("mail_provider")
if not provider:
    st.info("Connect a mailbox in the sidebar. No mailbox operation runs automatically.")
    st.stop()

scan_tab, review_tab, apply_tab = st.tabs(["Scan", "Review classifications", "Apply selected actions"])

with scan_tab:
    folders = st.session_state.get("folders", [])
    if provider.name == "gmail":
        folders = ["ALL"] + [item for item in folders if item != "ALL"]
    folder = st.selectbox("Folder or label to scan", folders)
    limit = st.number_input("Newest messages to scan", 1, 10000, 250, step=50)
    st.caption("Start with 100–250 messages, inspect accuracy, then increase the batch.")
    if st.button("Fetch and classify full messages", type="primary"):
        try:
            messages = provider.fetch_messages(folder, int(limit))
            classifier = SemanticClassifier(
                "ollama" if ai_provider.startswith("Local") else "openai_compatible",
                ai_url, ai_model, ai_key,
            )
            bar = st.progress(0, "Classifying")
            classified = classify_messages(
                messages, classifier,
                lambda current, total: bar.progress(current / max(total, 1), f"Classifying {current}/{total}"),
            )
            st.session_state.classified = classified
            st.success(f"Classified {len(classified)} messages. Review them before applying actions.")
        except Exception as exc:
            st.error(f"Scan failed: {exc}")

classified = st.session_state.get("classified", [])
with review_tab:
    if not classified:
        st.info("Run a scan first.")
    else:
        category_filter = st.multiselect("Categories", [item.value for item in Category],
                                         default=[item.value for item in Category])
        minimum = st.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.01)
        selection_preset = st.radio(
            "Mass selection",
            ["Recommended safe only", "Select every visible message", "Select none"],
            horizontal=True,
            help="Filter by category first, then select all visible results in one step.",
        )
        rows = []
        for message, classification in classified:
            if classification.category.value not in category_filter or classification.confidence < minimum:
                continue
            selected_by_default = recommended_action(classification) == Action.TRASH
            if selection_preset == "Select every visible message":
                selected_by_default = True
            elif selection_preset == "Select none":
                selected_by_default = False
            rows.append({
                "Selected": selected_by_default,
                "ID": message.provider_id,
                "Category": classification.category.value,
                "Confidence": round(classification.confidence, 3),
                "Protected": classification.protected,
                "Sender": message.sender,
                "Subject": message.subject,
                "Date": message.date,
                "Size_KB": round(message.size_bytes / 1024, 1),
                "Reason": classification.rationale,
            })
        edited = st.data_editor(
            pd.DataFrame(rows), hide_index=True, use_container_width=True, height=520,
            disabled=[column for column in rows[0] if column != "Selected"] if rows else None,
            key=f"review_editor_{selection_preset}_{hash(tuple(category_filter))}_{minimum}",
        )
        st.session_state.reviewed_rows = edited
        chosen = edited.loc[edited["Selected"]] if len(edited) else edited
        st.metric("Selected messages", len(chosen))
        if len(chosen) == 1:
            message_id = chosen.iloc[0]["ID"]
            message = next(item for item, _ in classified if item.provider_id == message_id)
            with st.expander("Full selected message preview"):
                st.text(message.classifier_text())

with apply_tab:
    reviewed = st.session_state.get("reviewed_rows")
    if reviewed is None or not len(reviewed):
        st.info("Select messages in the Review tab first.")
    else:
        selected = reviewed.loc[reviewed["Selected"]]
        action = Action(st.selectbox("Bulk action", [item.value for item in Action if item != Action.KEEP]))
        destination = ""
        if action in {Action.MOVE, Action.COPY, Action.CATEGORY}:
            if action == Action.CATEGORY and provider.name in {"gmail", "microsoft"}:
                destination = st.text_input("Category/label", "InboxOrganizer/Reviewed")
            else:
                destination = st.selectbox("Destination", st.session_state.get("folders", []))
        allow_protected = st.checkbox("Allow selected protected messages", False)
        st.error("Trash means move to the provider's recoverable Trash/Deleted Items folder. Permanent deletion is not implemented.")
        operations = []
        problems = []
        lookup = {message.provider_id: (message, result) for message, result in classified}
        for _, row in selected.iterrows():
            message, result = lookup[row["ID"]]
            try:
                operations.append(plan_operation(message, result, action, destination or None, allow_protected))
            except ValueError as exc:
                problems.append(f"{message.subject}: {exc}")
        if problems:
            st.warning("\n".join(problems[:20]))
        preview = pd.DataFrame([{
            "Subject": item.subject, "Category": item.category.value,
            "Confidence": item.confidence, "Action": item.action.value,
            "Destination": item.destination, "Protected": item.protected,
        } for item in operations])
        st.dataframe(preview, use_container_width=True)
        st.download_button("Download dry-run plan", preview.to_csv(index=False), "mailbox_action_plan.csv", "text/csv")
        required = "MOVE TO TRASH" if action == Action.TRASH else "APPLY"
        if action == Action.TRASH and allow_protected:
            required = "OVERRIDE PROTECTED AND MOVE TO TRASH"
        typed = st.text_input(f"Type {required} to confirm")
        if st.button("Apply mailbox changes", type="primary", disabled=not operations):
            try:
                policy_text = "MOVE TO TRASH" if typed == "OVERRIDE PROTECTED AND MOVE TO TRASH" else typed
                if typed != required:
                    raise ValueError("Confirmation text does not match")
                validate_confirmation(operations, policy_text)
                outcomes = apply_operations(provider, operations, str(AUDIT))
                failures = [item for item in outcomes if not item["status"].startswith("applied")]
                if failures:
                    st.error(f"Applied {len(outcomes)-len(failures)}; failed {len(failures)}. See local audit metadata.")
                else:
                    st.success(f"Applied {len(outcomes)} operations. Re-scan to refresh the view.")
            except Exception as exc:
                st.error(f"Nothing was applied: {exc}")
