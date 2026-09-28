import os
import sys
import tempfile

import streamlit as st

# parser.py does "from extractor import ...", so the document_processing folder
# itself has to be on the import path too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "document_processing"))

from document_processing.extractor import extract_pdf_text
from document_processing.parser import create_invoice_data
from document_processing.comparator import compare_invoices

st.set_page_config(page_title="Sovereign Executive", layout="wide")


# ---------- Backend glue ----------
def read_invoice(uploaded_file):
    """Uploaded PDF -> parsed invoice dict (same format the backend uses)."""
    # extract_pdf_text() needs a file path, so save the upload to a temp file first
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name
    try:
        pages = extract_pdf_text(tmp_path)
    finally:
        os.remove(tmp_path)
    text = "\n".join(page["text"] for page in pages)
    return create_invoice_data(text)


# ---------- Display logic ----------
def show_result(result):
    status = result["status"]

    if status == "ERROR":
        st.error(result.get("message", "Something went wrong."))
        return

    if status == "EXTRACTED":
        inv = result["invoice"]
        st.subheader(inv["vendor"]["name"] or "Vendor not detected")
        total = inv["amounts"]["total"]
        cur = inv["invoice"]["currency"] or ""
        c1, c2, c3 = st.columns(3)
        c1.metric("Invoice number", inv["invoice"]["number"] or "Not found")
        c2.metric("Invoice date", inv["invoice"]["date"] or "Not found")
        c3.metric("Total", f"{cur} {total:,.2f}".strip() if total is not None else "Not found")
        st.info("Invoice read successfully. Upload the previous invoice as well to run a comparison.")
        return

    st.subheader(result.get("vendor_name") or "Vendor not detected")
    cur = result.get("currency") or ""

    if status == "BASELINE_ESTABLISHED":
        st.success(result["message"])
        st.metric("Invoice total", f"{cur} {result['current_total']:,.2f}".strip())
        return

    # status == "SUCCESS" -> comparison
    c1, c2, c3 = st.columns(3)
    c1.metric("Previous total", f"{cur} {result['previous_total']:,.2f}".strip())
    c2.metric(
        "Current total",
        f"{cur} {result['current_total']:,.2f}".strip(),
        delta=f"{result['change_percentage']:+.2f}%",
        delta_color="inverse",  # an increase shows red
    )
    c3.metric("Change", f"{cur} {result['change_amount']:,.2f}".strip())
    st.caption(
        f"Invoices compared: {result['previous_invoice_number']} → {result['current_invoice_number']}"
    )

    st.markdown("### Flags")
    if not result["flags"]:
        st.success("No issues found.")
    for flag in result["flags"]:
        text = f"**{flag['type']}** ({flag['severity']}): {flag['description']}\n\nEvidence: {flag['evidence']}"
        if flag["severity"] == "HIGH":
            st.error(text)
        else:
            st.warning(text)

    # These two come from the AI part (Member 2). They only show up once it is connected.
    if result.get("ai_audit_note"):
        st.markdown("### AI audit note")
        st.info(result["ai_audit_note"])

    if result.get("dispute_email_draft"):
        st.markdown("### Dispute email draft")
        st.text_area("Edit before sending", value=result["dispute_email_draft"], height=220)


# ---------- Page ----------
st.title("Sovereign Executive")
st.subheader("The Air-Gapped Financial and Contract Auditor")
st.write("Upload invoices to check for suspicious changes. Fully offline, nothing leaves this device.")

col_prev, col_curr = st.columns(2)
prev_file = col_prev.file_uploader("Previous invoice (PDF)", type=["pdf"], key="prev")
curr_file = col_curr.file_uploader("Current invoice (PDF)", type=["pdf"], key="curr")

if st.button("Analyze Document"):
    if curr_file is None:
        st.warning("Please upload the current invoice first.")
    else:
        try:
            current = read_invoice(curr_file)
            if prev_file is None:
                st.session_state["result"] = {"status": "EXTRACTED", "invoice": current}
            else:
                previous = read_invoice(prev_file)
                st.session_state["result"] = compare_invoices(previous, current)
        except Exception as e:
            st.session_state["result"] = {"status": "ERROR", "message": f"Could not process the PDF: {e}"}

# Results live in session_state so they stay on screen when other widgets rerun the script
if "result" in st.session_state:
    show_result(st.session_state["result"])
