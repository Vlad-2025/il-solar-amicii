import streamlit as st

from app import common
from billing import stripe_checkout as sc
from db import repo
from db.seed import DEMO_EMAIL

user = common.user()

st.title("Abonament")
st.warning("**Mod de test: nu se percep bani reali.** La plată folosiți cardul de test Stripe "
           "**4242 4242 4242 4242**, orice dată de expirare din viitor și orice CVC.", icon=":material/science:")

# ---- returning from Stripe Checkout
qp = st.query_params
session_id = qp.get("session_id")
if session_id and not st.session_state.get(f"verified_{session_id}"):
    if repo.session_already_used(session_id):
        st.info("Această plată a fost deja confirmată.")
    else:
        try:
            res = sc.verify_session(session_id, user["id"])
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "status": f"eroare: {exc}"}
        if res["ok"]:
            repo.update_user(user["id"], plan="premium", stripe_customer_id=res.get("customer"))
            repo.add_subscription(user["id"], session_id, "active", res.get("period_end"))
            st.session_state[f"verified_{session_id}"] = True
            st.balloons()
            st.success("Plata de test a fost confirmată. Funcțiile Premium sunt deblocate.", icon=":material/verified:")
            user = common.user()
        else:
            st.error(f"Plata nu este finalizată (stare: {res.get('status')}).")
if qp.get("canceled"):
    st.info("Plata a fost anulată. Puteți reîncerca oricând.")

plan_premium = common.is_premium(user)
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("### Gratuit")
    st.markdown("- Explicarea facturii, rând cu rând\n- Bilanțul energiei (consumat, livrat, compensat)\n"
                "- Alerte când se schimbă legea, personalizate\n- Producția estimată pe 7 zile")
    if not plan_premium:
        st.caption("Planul dumneavoastră actual")
with c2, st.container(border=True):
    st.markdown("### Premium · 19 lei/lună")
    st.markdown("- Verificarea facturii cu datele invertorului\n- Recalcularea compensării după regula în vigoare\n"
                "- Prognoză pe ore: producție, consum, export, import\n- Factura estimată pentru luna curentă\n"
                "- Istoricul facturilor\n- Cerere de verificare pre-completată către furnizor")
    st.caption("Preț de test: îl validăm în interviuri.")
    if plan_premium:
        sub = repo.latest_subscription(user["id"])
        st.success("Planul dumneavoastră actual", icon=":material/workspace_premium:")
        if sub and sub.get("current_period_end"):
            st.caption(f"Perioada curentă se încheie pe {sub['current_period_end']:%d.%m.%Y}.")
    elif sc.configured():
        if st.button("Abonează-te (Stripe, mod de test)", type="primary", icon=":material/credit_card:",
                     width="stretch"):
            try:
                url = sc.create_checkout(user["email"], user["id"], common.app_url(), common.sign_login(user["id"]))
                st.session_state["checkout_url"] = url
            except Exception as exc:  # noqa: BLE001
                st.error(f"Nu am putut deschide plata: {exc}")
        if st.session_state.get("checkout_url"):
            st.link_button("Continuă la plata securizată Stripe", st.session_state["checkout_url"],
                           type="primary", icon=":material/open_in_new:", width="stretch")
    else:
        st.info("Stripe nu este configurat pe acest server (lipsesc STRIPE_SECRET_KEY și STRIPE_PRICE_ID).")
        if user["email"] == DEMO_EMAIL or user.get("is_admin"):
            if st.button("Activează Premium pentru demo (fără Stripe)", icon=":material/lock_open:",
                         width="stretch"):
                repo.update_user(user["id"], plan="premium")
                st.rerun()

if plan_premium:
    with st.expander("Anulare (mod de test)"):
        st.write("Revine la planul gratuit în aplicație. Într-un lansare reală, anularea ar trece prin portalul Stripe.")
        if st.button("Revino la planul gratuit", icon=":material/undo:"):
            repo.update_user(user["id"], plan="free")
            st.rerun()
