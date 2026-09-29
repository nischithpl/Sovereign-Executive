import os
import sys
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import ai_service, database
import analysis

st.set_page_config(page_title="Sovereign Executive", layout="wide")

COLORS = {"red": "#fecaca", "amber": "#fde68a", "green": "#bbf7d0"}


def fmt(x, cur=""):
    return f"{cur} {x:,.2f}".strip() if isinstance(x, (int, float)) else "Not found"


# ---------------------------------------------------------------- visuals
def waterfall(bridge):
    vals = [bridge["start"], bridge["end"]]
    run, rows = bridge["start"], []
    for s in bridge["steps"]:
        rows.append({"label": s["label"], "start": run, "end": run + s["value"],
                     "kind": "Increase" if s["value"] > 0 else "Decrease", "amount": s["value"]})
        run += s["value"]
        vals.append(run)
    floor = min(vals) * 0.9
    df = pd.DataFrame(
        [{"label": "Previous total", "start": floor, "end": bridge["start"], "kind": "Total", "amount": bridge["start"]}]
        + rows
        + [{"label": "Current total", "start": floor, "end": bridge["end"], "kind": "Total", "amount": bridge["end"]}]
    )
    return (
        alt.Chart(df).mark_bar().encode(
            x=alt.X("label:N", sort=None, title=None, axis=alt.Axis(labelAngle=-20)),
            y=alt.Y("start:Q", title=bridge["currency"], scale=alt.Scale(zero=False)),
            y2="end:Q",
            color=alt.Color("kind:N", legend=None, scale=alt.Scale(
                domain=["Total", "Increase", "Decrease"], range=["#64748b", "#dc2626", "#16a34a"])),
            tooltip=["label", "amount"],
        ).properties(height=320)
    )


def trend_table(trend):
    df = pd.DataFrame([[r["item"], *r["values"], r["delta"], r["status"]] for r in trend["rows"]],
                      columns=["Item", *trend["columns"], "Δ", "_status"])

    def style(row):
        return [f"background-color: {COLORS[row['_status']]}; color: #111" if c == "Δ" else "" for c in row.index]

    st.dataframe(df.style.apply(style, axis=1).hide(axis="columns", subset=["_status"]).format(precision=2, na_rep="—"),
                 use_container_width=True, hide_index=True)
    st.caption("Δ colour: 🟥 increase while a contract violation exists · 🟨 changed · 🟩 unchanged")


# ---------------------------------------------------------------- result display
def trend_table(trend):
    rows = trend.get("rows", [])
    columns = trend.get("columns", [])

    data = []

    for r in rows:
        values = list(r.get("values", []))

        # Make column names unique if the same invoice produces duplicates.
        row = {"Item": r.get("item", "")}

        for i, value in enumerate(values):
            col_name = columns[i] if i < len(columns) else f"Value {i + 1}"

            # Ensure duplicate column names don't break Pandas Styler.
            if col_name in row:
                col_name = f"{col_name} ({i + 1})"

            row[col_name] = value

        row["Δ"] = r.get("delta")
        row["_status"] = r.get("status")

        data.append(row)

    df = pd.DataFrame(data)

    def style(row):
        status = row.get("_status")
        delta_color = COLORS.get(status, "")

        return [
            f"background-color: {delta_color}; color: #111"
            if column == "Δ" and delta_color
            else ""
            for column in row.index
        ]

    st.dataframe(
        df.style
        .apply(style, axis=1)
        .hide(axis="columns", subset=["_status"])
        .format(precision=2, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Δ colour: 🟥 increase while a contract violation exists · "
        "🟨 changed · 🟩 unchanged"
    )


def show_email(result):
    if result.get("ai_audit_note"):
        st.markdown("### AI audit note")
        st.info(result["ai_audit_note"])
    if not result.get("dispute_email_draft"):
        st.write("No dispute email needed.")
        return
    if result.get("ai_source") == "template":
        st.caption(f"Local model unavailable ({result.get('ai_error')}), so this is a template built from the verified numbers.")
    else:
        st.caption("Drafted by the local model from code-verified numbers.")
    c1, c2 = st.columns([1, 3])
    tone = c1.selectbox("Tone", ["firm", "polite"], key="tone_pick")
    if c1.button("Regenerate email") and result.get("ai_args"):
        with st.spinner("Rewriting..."):
            ai = ai_service.generate_audit_summary(tone=tone, **result["ai_args"])
        result.update(ai_audit_note=ai["audit_note"], dispute_email_draft=ai["dispute_email"],
                      ai_source=ai["source"], ai_error=ai.get("error"),
                      ai_version=result.get("ai_version", 0) + 1)
        st.rerun()
    c2.text_area("Edit before sending", value=result["dispute_email_draft"], height=260,
                 key=f"email_{result.get('ai_version', 0)}")


def show_memory(result, cur):
    m = result.get("memory")
    if not m:
        return
    ls = m["last_seen"]
    st.markdown(f"**Vendor memory: {m['vendor']}** ({m['invoices_on_file']} invoice(s) on file)")
    st.write(f"Last seen: invoice {ls['invoice_number'] or '?'} · {fmt(ls['total'], cur)} · "
             f"GST {ls['tax_rate'] if ls['tax_rate'] is not None else '?'}% {ls['tax_type'] or ''} · "
             f"GSTIN {ls['gstin'] or 'missing'}")
    c = m.get("contract")
    if c:
        st.write(f"Contract: agreed {fmt(c.get('agreed_amount'), cur)} · cap {c.get('max_increase_pct')}% · "
                 f"renewal {c.get('renewal_date') or 'n/a'} (notice {c.get('notice_days') or 0} days)")
        if c.get("clause"):
            st.caption(f"Clause: {c['clause']}")
    else:
        st.caption("No contract on file. Add one in the sidebar to enable contract-compliance checks.")
    if m.get("cumulative_overpayment") is not None:
        st.metric("Cumulative overpayment vs contract (last 3 invoices)", fmt(m["cumulative_overpayment"], cur))


def show_tax(result, cur):
    t = result.get("tax_check")
    if not t:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tax rate", f"{t['rate']}%" if t["rate"] is not None else "n/a")
    c2.metric("Invoiced tax", fmt(t["invoiced"], cur))
    c3.metric("Recomputed (base × rate)", fmt(t["expected"], cur))
    c4.metric("Tax type", t["kind"] or "n/a")
    st.caption(f"Vendor GSTIN: {t['gstin'] or 'missing'}. Recomputation is plain arithmetic, not an LLM guess. "
               "Expected tax shows only when the invoice states its rate.")

def show_findings(result, cur):
    flags = result.get("flags", [])

    if not flags:
        st.success("No issues found.")
        return

    for f in flags:
        amt = f" · **{fmt(f['amount'], cur)}**" if f.get("amount") else ""

        text = (
            f"**{f['category']}** · {f['type']}{amt}\n\n"
            f"{f['description']}\n\n"
            f"{f['evidence']}"
        )

        if f["category"] == "VIOLATION":
            st.error(text)
        elif f["category"] == "UNEXPLAINED":
            st.warning(text)
        else:
            st.info(text)


def show_result(result):
    status = result["status"]
    if status == "ERROR":
        st.error(result.get("message", "Something went wrong."))
        return

    cur = result.get("currency") or "INR"
    st.subheader(result.get("vendor_name") or "Vendor not detected")
    if status == "DUPLICATE":
        st.error(result["message"])
    elif status == "BASELINE_ESTABLISHED":
        st.success(result["message"])

    lk = result.get("leakage", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Potentially recoverable", fmt(lk.get("recoverable"), cur))
    c2.metric("Contract violations", lk.get("violations", 0))
    c3.metric("Unexplained charges", lk.get("unexplained", 0))
    c4.metric("Projected annual impact", fmt(lk.get("projected_annual"), cur))

    r = (result.get("memory") or {}).get("renewal")
    if r and r["days_to_cancel"] <= 45:
        st.warning(f"Renewal alert: cancel by {r['cancel_by']} ({r['days_to_cancel']} days) · renews {r['renewal_date']}")
    if result.get("needs_review"):
        st.warning(f"Needs human review (confidence {result['confidence']:.0%}): " + ", ".join(result["confidence_reasons"]))
    else:
        st.caption(f"Extraction confidence: {result.get('confidence', 0):.0%}")

    if status == "SUCCESS":
        d1, d2, d3 = st.columns(3)
        d1.metric("Previous total", fmt(result["previous_total"], cur))
        d2.metric("Current total", fmt(result["current_total"], cur),
                  delta=f"{result['change_percentage']:+.2f}%", delta_color="inverse")
        d3.metric("Change", fmt(result["change_amount"], cur))
        st.caption(f"Invoices compared: {result['previous_invoice_number']} → {result['current_invoice_number']}")

    tabs = st.tabs(["Findings", "Comparison", "Tax check", "Vendor memory", "Dispute email", "Report"])
    with tabs[0]:
        show_findings(result, cur)
    with tabs[1]:
        if result.get("bridge") and result["bridge"]["steps"]:
            st.markdown("#### Why the bill changed")
            st.altair_chart(waterfall(result["bridge"]), use_container_width=True)
        if result.get("trend"):
            st.markdown("#### Invoice-to-invoice comparison")
            trend_table(result["trend"])
        if not result.get("trend"):
            st.info("Upload a second invoice (or a later one for the same vendor) to see the comparison.")
    with tabs[2]:
        show_tax(result, cur)
    with tabs[3]:
        show_memory(result, cur)
    with tabs[4]:
        show_email(result)
    with tabs[5]:
        md = analysis.build_report_md(result)
        st.download_button("Download report (Markdown)", md, file_name="audit_report.md")
        st.markdown(md)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    tone = st.selectbox("Dispute email tone", ["firm", "polite"])
    use_memory = st.checkbox("Use & update vendor memory", value=True,
                             help="Loads previous invoices from the local database and saves this one.")

    with st.expander("Contract terms (ground truth)"):
        default_vendor = (st.session_state.get("result") or {}).get("vendor_name", "")
        with st.form("contract_form"):
            v = st.text_input("Vendor name", value=default_vendor)
            agreed = st.number_input("Agreed price (pre-tax)", min_value=0.0, value=0.0)
            cap = st.number_input("Max annual increase %", min_value=0.0, value=0.0)
            renew = st.text_input("Renewal date (YYYY-MM-DD)")
            notice = st.number_input("Notice days", min_value=0, value=30)
            clause = st.text_input("Price clause (quoted in emails)", placeholder="Clause 4.2, page 3: price fixed for 12 months")
            if st.form_submit_button("Save contract"):
                try:
                    if renew:
                        datetime.strptime(renew, "%Y-%m-%d")
                    if not v.strip():
                        raise ValueError("Vendor name is required")
                    database.save_contract(v, agreed or None, cap or None, renew or None, int(notice), clause or None)
                    st.success("Contract saved.")
                except ValueError as e:
                    st.error(f"Invalid input: {e}")

    st.subheader("Renewal calendar")
    cal = [(c["vendor_name"], analysis.renewal_info(c)) for c in database.list_contracts()]
    cal = sorted([(n, r) for n, r in cal if r], key=lambda x: x[1]["days_to_cancel"])
    if not cal:
        st.caption("No renewals tracked yet.")
    for name, r in cal:
        icon = "🔴" if r["days_to_cancel"] < 0 else "🟠" if r["days_to_cancel"] <= 30 else "🟢"
        st.write(f"{icon} **{name}**: cancel by {r['cancel_by']} ({r['days_to_cancel']}d)")

# ---------------------------------------------------------------- page
st.title("Sovereign Executive")
st.subheader("The Air-Gapped Financial and Contract Auditor")
st.write("Upload invoices to check for suspicious changes. Fully offline, nothing leaves this device.")

col_prev, col_curr = st.columns(2)
prev_file = col_prev.file_uploader("Previous invoice (PDF, optional if vendor is already in memory)", type=["pdf"], key="prev")
curr_file = col_curr.file_uploader("Current invoice (PDF)", type=["pdf"], key="curr")

if st.button("Analyze Document", type="primary"):
    if curr_file is None:
        st.warning("Please upload the current invoice first.")
    else:
        try:
            with st.spinner("Reading, comparing, and drafting..."):
                current = analysis.parse_pdf_bytes(curr_file.getvalue())
                previous = analysis.parse_pdf_bytes(prev_file.getvalue()) if prev_file is not None else None
                st.session_state["result"] = analysis.run_audit(
                    current, previous, tone=tone, save=use_memory, use_memory=use_memory)
        except Exception as e:
            st.session_state["result"] = {"status": "ERROR", "message": f"Could not process the PDF: {e}"}

# Results live in session_state so they stay on screen when other widgets rerun the script
if "result" in st.session_state:
    show_result(st.session_state["result"])

# ---------------------------------------------------------------- bank reconciliation
st.divider()
with st.expander("Bank reconciliation (invoices vs actual debits)"):
    bank = st.file_uploader("Bank statement (CSV with date, description/narration, debit/amount)", type=["csv"], key="bank")
    if bank is not None and st.button("Reconcile"):
        rec = analysis.reconcile_bank(bank.getvalue(), database.list_invoices())
        if rec.get("error"):
            st.error(rec["error"])
        else:
            st.success(f"{len(rec['matched'])} invoice(s) matched to a bank debit.")
            if rec["invoices_without_debit"]:
                st.warning("Invoices with no matching debit (unpaid or paid differently):")
                st.dataframe(pd.DataFrame(rec["invoices_without_debit"]), hide_index=True)
            if rec["debits_without_invoice"]:
                st.error("Bank debits with no matching invoice (possible unauthorised charge):")
                st.dataframe(pd.DataFrame(rec["debits_without_invoice"]), hide_index=True)
            if rec["matched"]:
                st.dataframe(pd.DataFrame(rec["matched"]), hide_index=True)
