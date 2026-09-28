import streamlit as st
import pandas as pd

# ---- Page setup ----
st.set_page_config(page_title="Sovereign Executive", layout="wide")

st.title("Sovereign Executive")
st.subheader("The Air-Gapped Financial and Contract Auditor")
st.write("Upload an invoice or contract to check for suspicious changes — fully offline, nothing leaves this device.")

# ---- File upload ----
uploaded_file = st.file_uploader("Upload a document (PDF)", type=["pdf"])

if uploaded_file is not None:
    st.success(f"Uploaded: {uploaded_file.name}")

# ---- Analyze button ----
if st.button("Analyze Document"):
    if uploaded_file is None:
        st.warning("Please upload a file first.")
    else:
        st.info("Analyzing... (this is dummy data for now — will connect to backend later)")

        # ---- Dummy results table ----
        # This is placeholder data. Once Member 1/2/3 build the real
        # extraction + comparison logic, this table gets replaced with
        # their actual output.
        dummy_results = pd.DataFrame({
            "Field": ["Invoice Amount", "Vendor Name", "Renewal Clause", "Payment Terms"],
            "Previous Value": ["₹10,000", "Acme Supplies", "None", "Net 30"],
            "Current Value": ["₹12,000", "Acme Supplies", "Auto-renews +15%", "Net 15"],
            "Flag": ["⚠️ Price increase (20%)", "OK", "⚠️ New clause detected", "⚠️ Changed"]
        })

        st.dataframe(dummy_results, use_container_width=True)

        st.markdown("---")
        st.subheader("Suggested Action")
        st.write("This invoice shows a 20% price increase and a new auto-renewal clause not present in the previous version. Consider disputing this charge.")

        if st.button("Generate Dispute Email"):
            st.text_area(
                "Draft Email",
                value="Subject: Query Regarding Recent Invoice Changes\n\nHi [Vendor],\n\nWe noticed the latest invoice reflects a 20% increase from the previous amount, along with a new auto-renewal clause. Could you clarify the reason for these changes?\n\nThanks,\n[Your Name]",
                height=200
            )
