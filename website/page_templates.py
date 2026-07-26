"""Odoo website QWeb arch templates for PetSpot El Sahel."""
from __future__ import annotations

from typing import Any

from schema_ld import faq_ld, organization_ld, script_tag, veterinary_care_ld


def _cta_row(c: dict[str, Any]) -> str:
    wa = c["whatsapp_url"]
    maps = c["maps_url"]
    phone_tel = c["phone_tel"]
    cc = c.get("call_center_tel") or ""
    cc_btn = (
        f'<a class="btn btn-outline-secondary" href="tel:{cc}">'
        f'<i class="fa fa-headphones me-1"/> Call center</a>'
        if cc
        else ""
    )
    return f"""
<div class="d-flex flex-wrap gap-2">
  <a class="btn btn-success" href="{wa}" target="_blank" rel="noopener">
    <i class="fa fa-whatsapp me-1"/> WhatsApp</a>
  <a class="btn btn-primary" href="tel:{phone_tel}">
    <i class="fa fa-phone me-1"/> Call clinic</a>
  {cc_btn}
  <a class="btn btn-outline-primary" href="{maps}" target="_blank" rel="noopener">
    <i class="fa fa-map-marker me-1"/> Directions</a>
  <a class="btn btn-outline-dark" href="/appointment">Book appointment</a>
</div>"""


def _contact_block(c: dict[str, Any]) -> str:
    return f"""
<p><strong>Primary phone:</strong>
  <a href="tel:{c["phone_tel"]}"><span class="o_force_ltr">{c["phone"]}</span></a></p>
<p><strong>Call center:</strong>
  <a href="tel:{c["call_center_tel"]}"><span class="o_force_ltr">{c["call_center"]}</span></a></p>
<p><strong>WhatsApp:</strong>
  <a href="{c["whatsapp_url"]}" target="_blank" rel="noopener">010 00059085</a></p>
<p><strong>Address:</strong> {c["address_en"]}</p>
<p dir="rtl"><strong>العنوان:</strong> {c["address_ar"]}</p>
<p><strong>Hours:</strong> {c["hours_en"]}</p>
<p dir="rtl"><strong>المواعيد:</strong> {c["hours_ar"]}</p>
<p><strong>Emergency:</strong> {c["emergency_en"]}</p>
<p dir="rtl"><strong>الطوارئ:</strong> {c["emergency_ar"]}</p>
"""


def _service_cards(c: dict[str, Any]) -> str:
    rows = []
    wa = c["whatsapp_url"]
    phone_tel = c["phone_tel"]
    gallery_urls = c.get("gallery_urls") or {}
    for svc in c["services"]:
        if svc.get("id") == "emergency":
            cta_href = f"tel:{phone_tel}"
        else:
            cta_href = wa
        color = svc.get("color", "#1a5f7a")
        slot_id = svc.get("gallery_slot")
        image_url = gallery_urls.get(slot_id) if slot_id else None
        if image_url:
            style = (
                f"background: linear-gradient(165deg, {color}e6 0%, {color}bf 55%, {color}99 100%), "
                f"url('{image_url}') center/cover no-repeat;"
            )
        else:
            style = (
                f"background: linear-gradient(165deg, {color} 0%, {color}dd 45%, {color}bb 100%);"
            )
        icon = svc.get("icon", "fa-paw")
        rows.append(
            f"""<div class="col-md-6 col-lg-4">
  <div class="card h-100 border-0 shadow-sm overflow-hidden">
    <div class="card-body d-flex flex-column text-white p-4"
         style="min-height:280px; {style}">
      <div class="mb-3 opacity-75"><i class="fa {icon} fa-2x"/></div>
      <h5 class="fw-bold mb-1">{svc["title_en"]}</h5>
      <p dir="rtl" class="small mb-2 opacity-90">{svc["title_ar"]}</p>
      <p class="small mb-2 opacity-90">{svc["desc_en"]}</p>
      <p dir="rtl" class="small mb-3 opacity-90">{svc["desc_ar"]}</p>
      <a class="btn btn-light btn-sm mt-auto align-self-start" href="{cta_href}"
         target="_blank" rel="noopener">{svc.get("cta_en", "Book")}</a>
    </div>
  </div>
</div>"""
        )
    return "\n".join(rows)


def _gallery_items(c: dict[str, Any]) -> str:
    rows = []
    gallery_items = c.get("gallery_items")
    if gallery_items:
        for item in gallery_items:
            rows.append(
                f"""<div class="col-6 col-md-4 col-lg-3">
  <img src="{item["url"]}" alt="{item["alt"]}" class="img-fluid rounded shadow-sm w-100"
       style="min-height:200px; object-fit:cover;"/>
</div>"""
            )
        return "\n".join(rows)

    gallery_urls = c.get("gallery_urls") or {}
    for slot in c["gallery_slots"]:
        url = gallery_urls.get(slot["id"])
        if url:
            rows.append(
                f"""<div class="col-6 col-md-4 col-lg-3">
  <img src="{url}" alt="{slot["alt"]}" class="img-fluid rounded shadow-sm w-100"
       style="min-height:200px; object-fit:cover;"/>
</div>"""
            )
        else:
            rows.append(
                f"""<div class="col-6 col-md-4 col-lg-3">
  <div class="border rounded bg-light d-flex align-items-center justify-content-center text-center p-4"
       style="min-height:200px;" role="img" aria-label="{slot["alt"]}">
    <div>
      <i class="fa fa-camera fa-2x text-muted mb-2"/>
      <p class="small text-muted mb-0">{slot["alt"]}</p>
    </div>
  </div>
</div>"""
            )
    return "\n".join(rows)


def _faq_html(faqs: list[tuple[str, str, str, str]]) -> str:
    """faqs: (q_en, a_en, q_ar, a_ar)"""
    blocks = []
    for q_en, a_en, q_ar, a_ar in faqs:
        blocks.append(
            f"""<div class="mb-4">
  <h3 class="h5">{q_en}</h3>
  <p>{a_en}</p>
  <h4 class="h6" dir="rtl">{q_ar}</h4>
  <p dir="rtl">{a_ar}</p>
</div>"""
        )
    return "\n".join(blocks)


HOME_FAQS = [
    (
        "Where is pet.spot?",
        "We are on Egypt's North Coast on the main road beside Amwaj Gate 1, beside Amwaj Gate 1 on the Main Road, Sidi Abdel Rahman, North Coast. Use Directions for the Maps pin.",
        "أين يقع pet.spot؟",
        "بجوار بوابة أمواج 1 على الطريق الرئيسي، سيدي عبد الرحمن، الساحل الشمالي. استخدم زر الاتجاهات لفتح الموقع على خرائط جوجل.",
    ),
    (
        "Are you open 24/7?",
        "Yes. The clinic and emergency veterinary service operate 24 hours, seven days a week.",
        "هل أنتم مفتوحون على مدار الساعة؟",
        "نعم. العيادة وخدمة الطوارئ البيطرية تعملان 24 ساعة طوال أيام الأسبوع.",
    ),
    (
        "Which number should I call?",
        "Call the clinic on 01280833332. For the call center use 01201568888. WhatsApp is 01000059085.",
        "أي رقم أتصل به؟",
        "عيادة: 01280833332 · مركز الاتصال: 01201568888 · واتساب: 01000059085.",
    ),
]


def build_homepage_arch(c: dict[str, Any]) -> str:
    b = c["brand"]
    phone_tel = c["phone_tel"]
    wa = c["whatsapp_url"]
    maps = c["maps_url"]
    fb = c["facebook"]
    ig = c["instagram"]
    logo_url = c.get("logo_url", "/web/image/res.company/1/logo")
    hero_url = c.get("hero_image_url", "")
    grooming_url = (c.get("gallery_urls") or {}).get("grooming", "")
    clinic_front_url = (c.get("gallery_urls") or {}).get("clinic_front", "")
    hero_col = ""
    if hero_url:
        hero_col = f"""<div class="col-lg-6 order-lg-2 text-center">
              <div class="p-2 p-lg-0">
                <img src="{hero_url}" alt="{b["name_en"]} — veterinary clinic near Amwaj Gate 1"
                     class="img-fluid rounded-3 shadow-lg"
                     style="max-height:460px; width:100%; object-fit:contain; object-position:center;"/>
              </div>
            </div>"""
    about_image = (
        f'<img src="{clinic_front_url}" alt="{b["name_en"]} clinic" '
        f'class="img-fluid rounded shadow-sm w-100" style="max-height:400px; object-fit:cover;"/>'
        if clinic_front_url
        else '<div class="border rounded bg-light p-5 text-muted text-center"><i class="fa fa-hospital-o fa-3x mb-3"/></div>'
    )
    ld = script_tag(
        veterinary_care_ld(c),
        organization_ld(c),
        faq_ld([(q, a) for q, a, _, _ in HOME_FAQS]),
    )
    faq_block = _faq_html(HOME_FAQS)
    cta = _cta_row(c)

    banner_en = b.get(
        "location_banner_en",
        "Pet.spot is beside Amwaj Gate 1 on the Main Road — veterinary care and emergency service available 24/7.",
    )
    banner_ar = b.get(
        "location_banner_ar",
        "Pet.spot بجوار بوابة أمواج 1 على الطريق الرئيسي — رعاية بيطرية وطوارئ على مدار 24 ساعة.",
    )
    relocate_banner = f"""
      <section class="o_petspot_location_banner" data-name="Location banner"
               style="background-color:#0f3d4c;">
        <div class="container py-3">
          <a href="{maps}" target="_blank" rel="noopener"
             class="d-block text-decoration-none text-white">
            <p class="mb-1 fw-semibold" dir="rtl">{banner_ar}</p>
            <p class="mb-0 small" style="opacity:0.92;">{banner_en}</p>
          </a>
        </div>
      </section>"""

    return f"""<t name="Homepage" t-name="website.homepage">
  <t t-call="website.layout" pageName.f="homepage">
    <div id="wrap" class="oe_structure">
      {ld}
      {relocate_banner}
      <section class="s_cover pt48 pb64 o_colored_level" data-snippet="s_cover" data-name="Hero"
               style="background: linear-gradient(135deg, #1a5f7a 0%, #2d8f6f 100%);">
        <div class="container">
          <div class="row align-items-center g-4">
            <div class="col-lg-6 order-lg-1">
              <h1 class="display-5 fw-bold text-white mb-1">{b["name_en"]}</h1>
              <p class="h5 text-white-50 mb-4" dir="rtl">{b["name_ar"]}</p>
              <p class="h4 text-white fw-semibold mb-1">{b["tagline_en"]}</p>
              <p class="h5 text-white mb-4" dir="rtl">{b["tagline_ar"]}</p>
              <p class="lead text-white mb-2" style="opacity:0.92;">{b["subheadline_en"]}</p>
              <p class="mb-4 text-white" dir="rtl" style="opacity:0.85;">{b["subheadline_ar"]}</p>
              <div class="d-grid gap-2" style="max-width:480px;">
                <a class="btn btn-success btn-lg" href="{wa}" target="_blank" rel="noopener">
                  <i class="fa fa-whatsapp me-2"/> Book on WhatsApp · احجز على واتساب
                </a>
                <div class="row g-2">
                  <div class="col-4">
                    <a class="btn btn-light w-100" href="{maps}" target="_blank" rel="noopener">Directions</a>
                  </div>
                  <div class="col-4">
                    <a class="btn btn-outline-light w-100" href="tel:{phone_tel}">Call</a>
                  </div>
                  <div class="col-4">
                    <a class="btn btn-outline-light w-100" href="/appointment">Book</a>
                  </div>
                </div>
              </div>
            </div>
            {hero_col}
          </div>
        </div>
      </section>

      <section class="s_features pt64 pb64" style="background-color:#fff8f5;" data-snippet="s_features" data-name="Why choose us">
        <div class="container">
          <div class="text-center mb-5">
            <h2>Why choose PetSpot El Sahel</h2>
            <h3 dir="rtl" class="h4">لماذا بيت سبوت الساحل</h3>
          </div>
          <div class="row text-center g-4">
            <div class="col-md-3"><div class="p-3"><i class="fa fa-clock-o fa-2x text-primary mb-2"/><h5>Open 24/7</h5><p class="text-muted">Clinic and emergency care every day.</p><p dir="rtl" class="mb-0 small">عيادة وطوارئ كل يوم.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-map-marker fa-2x text-primary mb-2"/><h5>Near Amwaj Gate 1</h5><p class="text-muted">Main road beside Amwaj Gate 1, North Coast.</p><p dir="rtl" class="mb-0 small">بجوار بوابة أمواج 1 على الطريق الرئيسي.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-stethoscope fa-2x text-primary mb-2"/><h5>Full pet services</h5><p class="text-muted">Clinic, vaccines, grooming, boarding, home visits.</p><p dir="rtl" class="mb-0 small">عيادة وتطعيمات وجرومينج وبوردينج وزيارات.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-whatsapp fa-2x text-success mb-2"/><h5>Easy WhatsApp booking</h5><p class="text-muted">Message 01000059085 to book.</p><p dir="rtl" class="mb-0 small">احجز عبر واتساب.</p></div></div>
          </div>
        </div>
      </section>

      <section id="services" class="s_three_columns pt64 pb64 bg-200" data-snippet="s_three_columns" data-name="Services">
        <div class="container">
          <div class="text-center mb-5">
            <h2>Our Services</h2>
            <h3 dir="rtl" class="h4">خدماتنا</h3>
          </div>
          <div class="row g-4">{_service_cards(c)}</div>
          <div class="text-center mt-4">
            <a class="btn btn-link" href="/emergency-vet-north-coast">24/7 emergency</a> ·
            <a class="btn btn-link" href="/veterinary-clinic-near-amwaj">Near Amwaj</a> ·
            <a class="btn btn-link" href="/veterinary-home-visits-sahel">Home visits</a> ·
            <a class="btn btn-link" href="/pet-vaccinations-north-coast">Vaccinations</a> ·
            <a class="btn btn-link" href="/grooming-boarding-sahel">Grooming &amp; boarding</a> ·
            <a class="btn btn-link" href="/blog">Pet care guide</a>
          </div>
        </div>
      </section>

      <section class="s_text_block pt64 pb64" style="background-color:#fff8f5;" data-snippet="s_text_block" data-name="Boarding Grooming">
        <div class="container">
          <div class="row g-4 align-items-center">
            <div class="col-lg-6">
              <h2>Grooming &amp; Boarding</h2>
              <h3 dir="rtl" class="h4">الجروومينج والبوردينج</h3>
              <p>Professional grooming and supervised boarding for North Coast stays. Ask our team about daily and short-stay options.</p>
              <p dir="rtl">جرومينج احترافي وبوردينج تحت الإشراف أثناء الإقامة في الساحل. اسألوا عن الخيارات اليومية أو القصيرة.</p>
              <a class="btn btn-primary me-2" href="{wa}" target="_blank" rel="noopener">WhatsApp</a>
              <a class="btn btn-outline-primary" href="/grooming-boarding-sahel">Learn more</a>
            </div>
            <div class="col-lg-6">
              {(
                f'<img src="{grooming_url}" alt="PetSpot grooming and boarding" '
                f'class="img-fluid rounded shadow-sm w-100" style="max-height:360px; object-fit:cover;"/>'
                if grooming_url
                else '<div class="border rounded bg-light p-5 text-center text-muted"><i class="fa fa-paw fa-3x mb-3"/></div>'
              )}
            </div>
          </div>
        </div>
      </section>

      <section id="gallery" class="s_images_wall pt64 pb64" data-snippet="s_images_wall" data-name="Gallery">
        <div class="container">
          <div class="text-center mb-5">
            <h2>Clinic Gallery</h2>
            <h3 dir="rtl" class="h4">معرض العيادة</h3>
          </div>
          <div class="row g-3">{_gallery_items(c)}</div>
        </div>
      </section>

      <section class="s_text_block pt64 pb64 bg-200" data-snippet="s_text_block" data-name="About">
        <div class="container">
          <div class="row align-items-center g-4">
            <div class="col-lg-6">
              <h2>About {c["company_name"]}</h2>
              <h3 dir="rtl" class="h4 mb-3">{b["name_ar"]}</h3>
              <p>{b["positioning_en"]}</p>
              <p dir="rtl">{b["positioning_ar"]}</p>
              {_contact_block(c)}
              {cta}
            </div>
            <div class="col-lg-6 text-center">{about_image}</div>
          </div>
        </div>
      </section>

      <section id="location" class="s_text_block pt64 pb64" style="background-color:#fff8f5;" data-snippet="s_text_block" data-name="Location">
        <div class="container">
          <div class="text-center mb-4">
            <h2>Find us near Amwaj Gate 1</h2>
            <h3 dir="rtl" class="h4">موقعنا بجوار بوابة أمواج 1</h3>
          </div>
          <div class="row g-4">
            <div class="col-lg-5">
              {_contact_block(c)}
              {cta}
            </div>
            <div class="col-lg-7">
              <div class="border rounded bg-light p-5 text-center" style="min-height:280px;">
                <i class="fa fa-map-marker fa-3x text-primary mb-3"/>
                <p class="lead mb-2">{c["address_en"]}</p>
                <p dir="rtl" class="mb-4">{c["address_ar"]}</p>
                <a class="btn btn-primary btn-lg" href="{maps}" target="_blank" rel="noopener">Open in Google Maps</a>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="s_faq pt64 pb64 bg-200" data-snippet="s_faq" data-name="FAQ">
        <div class="container">
          <div class="text-center mb-4">
            <h2>Frequently asked questions</h2>
            <h3 dir="rtl" class="h4">أسئلة شائعة</h3>
          </div>
          {faq_block}
        </div>
      </section>

      <section class="s_call_to_action pt64 pb64 o_cc o_cc1" data-snippet="s_call_to_action" data-name="Social CTA">
        <div class="container text-center">
          <h2>Follow &amp; book with PetSpot</h2>
          <p dir="rtl" class="lead">تابعونا واحجزوا بسهولة</p>
          <div class="d-flex flex-wrap justify-content-center gap-3 mt-3">
            <a class="btn btn-primary btn-lg" href="{fb}" target="_blank" rel="noopener"><i class="fa fa-facebook me-2"/> Facebook</a>
            <a class="btn btn-danger btn-lg" href="{ig}" target="_blank" rel="noopener"><i class="fa fa-instagram me-2"/> Instagram</a>
            <a class="btn btn-success btn-lg" href="{wa}" target="_blank" rel="noopener"><i class="fa fa-whatsapp me-2"/> WhatsApp</a>
          </div>
          <p class="mt-4 mb-0"><a href="/contact-directions-booking">Contact, directions &amp; booking</a>
            · <a href="mailto:{c["email"]}">{c["email"]}</a>
            · <a href="/blog">Pet care guide</a></p>
        </div>
      </section>
    </div>
  </t>
</t>"""


def build_contact_arch(c: dict[str, Any]) -> str:
    b = c["brand"]
    ld = script_tag(veterinary_care_ld(c, c["website_url"].rstrip("/") + "/contactus"))
    return f"""<t name="Contact Us" t-name="website.contactus">
  <t t-call="website.layout">
    <t t-set="logged_partner" t-value="request.env['website.visitor']._get_visitor_from_request().partner_id"/>
    <t t-set="contactus_form_values" t-value="{{
        'email_to': res_company.email,
        'name': request.params.get('name', ''),
        'phone': request.params.get('phone', ''),
        'email_from': request.params.get('email_from', ''),
        'company': request.params.get('company', ''),
        'subject': request.params.get('subject', ''),
    }}"/>
    <span class="hidden" data-for="contactus_form" t-att-data-values="contactus_form_values"/>
    <div id="wrap" class="oe_structure">
      {ld}
      <section class="s_title pt48 pb24" data-snippet="s_title">
        <div class="container text-center">
          <h1>Contact, directions &amp; booking</h1>
          <h2 dir="rtl" class="h4">تواصل · اتجاهات · حجز</h2>
          <p class="lead">{c["company_name"]}</p>
          <p dir="rtl" class="lead">{b["name_ar"]}</p>
        </div>
      </section>
      <section class="s_text_block pb24" data-snippet="s_text_block">
        <div class="container">
          <div class="row justify-content-center">
            <div class="col-lg-8">
              {_contact_block(c)}
              {_cta_row(c)}
              <p class="text-center mt-4">
                <a class="btn btn-outline-primary" href="{c["facebook"]}" target="_blank" rel="noopener">Facebook</a>
                <a class="btn btn-outline-danger ms-2" href="{c["instagram"]}" target="_blank" rel="noopener">Instagram</a>
              </p>
            </div>
          </div>
        </div>
      </section>
      <section class="s_website_form pt24 pb64" data-snippet="s_website_form">
        <div class="container">
          <div class="row">
            <div class="col-lg-8 offset-lg-2">
              <form id="contactus_form" action="/website/form/" method="post" enctype="multipart/form-data"
                    class="o_mark_required" data-mark="*" data-model_name="mail.mail"
                    data-success-mode="redirect" data-success-page="/contactus-thank-you" data-pre-fill="true">
                <div class="mb-3">
                  <label class="form-label" for="contact_name">Your Name / الاسم</label>
                  <input type="text" class="form-control" name="name" required="required" id="contact_name"/>
                </div>
                <div class="mb-3">
                  <label class="form-label" for="contact_phone">Phone / الهاتف</label>
                  <input type="tel" class="form-control" name="phone" id="contact_phone"/>
                </div>
                <div class="mb-3">
                  <label class="form-label" for="contact_email">Email</label>
                  <input type="email" class="form-control" name="email_from" id="contact_email"/>
                </div>
                <div class="mb-3">
                  <label class="form-label" for="contact_message">Message / الرسالة</label>
                  <textarea class="form-control" name="description" rows="4" required="required" id="contact_message"/>
                </div>
                <button type="submit" class="btn btn-primary">Send / إرسال</button>
              </form>
            </div>
          </div>
        </div>
      </section>
    </div>
  </t>
</t>"""


def build_footer_inherit_arch(c: dict[str, Any]) -> str:
    b = c["brand"]
    return f"""<data>
  <xpath expr="//div[@id='footer']" position="replace">
    <div id="footer" class="oe_structure oe_structure_solo border text-break" t-ignore="true" t-if="not no_footer">
      <section class="s_text_block pt40 pb16" data-snippet="s_text_block" data-name="PetSpot Footer">
        <div class="container">
          <div class="row">
            <div class="col-lg-3 pt24 pb24">
              <h5>Useful Links</h5>
              <ul class="list-unstyled">
                <li><a href="/">Home</a></li>
                <li><a href="/#services">Services</a></li>
                <li><a href="/emergency-vet-north-coast">Emergency 24/7</a></li>
                <li><a href="/blog">Pet care guide</a></li>
                <li><a href="/contact-directions-booking">Contact &amp; booking</a></li>
              </ul>
            </div>
            <div class="col-lg-5 pt24 pb24">
              <h5>{c["company_name"]}</h5>
              <p>{b["positioning_en"]}</p>
              <p dir="rtl">{b["positioning_ar"]}</p>
              <p class="mb-0"><strong>{c["address_en"]}</strong></p>
              <p dir="rtl" class="mb-0"><strong>{c["address_ar"]}</strong></p>
              <p class="text-muted small mt-2 mb-0">{c["hours_en"]} · {c["hours_ar"]}</p>
            </div>
            <div class="col-lg-4 pt24 pb24">
              <h5>Connect</h5>
              <ul class="list-unstyled">
                <li><i class="fa fa-phone fa-fw me-2"/><a href="tel:{c["phone_tel"]}"><span class="o_force_ltr">{c["phone"]}</span></a> (clinic)</li>
                <li><i class="fa fa-headphones fa-fw me-2"/><a href="tel:{c["call_center_tel"]}"><span class="o_force_ltr">{c["call_center"]}</span></a> (call center)</li>
                <li><i class="fa fa-whatsapp fa-fw me-2"/><a href="{c["whatsapp_url"]}" target="_blank" rel="noopener">WhatsApp 01000059085</a></li>
                <li><i class="fa fa-envelope fa-fw me-2"/><a href="mailto:{c["email"]}">{c["email"]}</a></li>
                <li><i class="fa fa-facebook fa-fw me-2"/><a href="{c["facebook"]}" target="_blank" rel="noopener">Facebook</a></li>
                <li><i class="fa fa-instagram fa-fw me-2"/><a href="{c["instagram"]}" target="_blank" rel="noopener">Instagram</a></li>
                <li><i class="fa fa-map-marker fa-fw me-2"/><a href="{c["maps_url"]}" target="_blank" rel="noopener">Google Maps</a></li>
              </ul>
            </div>
          </div>
        </div>
      </section>
    </div>
  </xpath>
  <xpath expr="//footer//span[hasclass('o_footer_copyright_name')]" position="replace">
    <span class="o_footer_copyright_name me-2 small">Copyright &amp;copy; {c["company_name"]}</span>
  </xpath>
</data>"""


SERVICE_PAGES: list[dict[str, Any]] = [
    {
        "url": "/emergency-vet-north-coast",
        "name": "24/7 Emergency Vet North Coast",
        "title": "24/7 Emergency Veterinarian North Coast | PetSpot El Sahel",
        "meta": "24/7 emergency veterinary care near Amwaj Gate 1 on Egypt's North Coast. Call 01280833332 or WhatsApp 01000059085.",
        "h1_en": "24/7 emergency veterinarian — North Coast",
        "h1_ar": "طبيب بيطري للطوارئ على مدار الساعة — الساحل الشمالي",
        "body_en": (
            "If your pet is injured, struggling to breathe, collapsing, seizuring, or has ingested something toxic, "
            "contact PetSpot El Sahel Veterinary Clinic immediately. We provide emergency veterinary support "
            "24 hours a day near Amwaj Gate 1. This page does not diagnose your pet online — urgent cases need direct contact."
        ),
        "body_ar": (
            "إذا كان أليفك مصابًا أو يتنفس بصعوبة أو منهكًا أو يعاني تشنجات أو ابتلع مادة ضارة، "
            "تواصل فورًا مع عيادة بيت سبوت الساحل. نوفر دعمًا بيطريًا للطوارئ على مدار الساعة بجوار بوابة أمواج 1. "
            "هذه الصفحة لا تشخّص عن بُعد — الحالات العاجلة تحتاج تواصلًا مباشرًا."
        ),
        "faqs": [
            (
                "What is an emergency?",
                "Difficulty breathing, uncontrolled bleeding, collapse, seizures, toxin ingestion, severe vomiting/diarrhea, or sudden inability to walk. When unsure, call us.",
                "ما هي حالة الطوارئ؟",
                "صعوبة التنفس، نزيف غير مسيطر عليه، إغماء، تشنجات، سموم، قيء/إسهال شديد، أو عدم القدرة على المشي. عند الشك اتصلوا بنا.",
            ),
        ],
        "links": [("/veterinary-clinic-near-amwaj", "Clinic near Amwaj"), ("/blog", "Pet care guide")],
    },
    {
        "url": "/veterinary-clinic-near-amwaj",
        "name": "Veterinary Clinic near Amwaj",
        "title": "Veterinary Clinic near Amwaj Gate 1 | PetSpot El Sahel",
        "meta": "Veterinary clinic beside Amwaj Gate 1 on the Main Road, Sidi Abdel Rahman. 24/7 care, vaccinations, grooming and boarding.",
        "h1_en": "Veterinary clinic near Amwaj Gate 1",
        "h1_ar": "عيادة بيطرية بجوار بوابة أمواج 1",
        "body_en": (
            "PetSpot El Sahel Veterinary Clinic is located on the North Coast beside Amwaj Gate 1 on the Main Road, Sidi Abdel Rahman, "
            "El Alamein. Use our Google Maps directions link for the verified pin. We welcome dogs, cats and companion pets "
            "for consultations, vaccines, grooming, boarding and urgent care."
        ),
        "body_ar": (
            "عيادة بيت سبوت الساحل تقع على الساحل الشمالي بجوار بوابة أمواج 1 على الطريق الرئيسي بسيدي عبد الرحمن. "
            "استخدموا رابط خرائط جوجل للموقع الموثق. نستقبل الكلاب والقطط والحيوانات الأليفة للكشف والتطعيم والجرومينج والبوردينج والطوارئ."
        ),
        "faqs": [
            (
                "Do you serve Amwaj resorts?",
                "Yes — we are positioned for owners staying around Amwaj Gate 1 and nearby North Coast compounds.",
                "هل تخدمون منتجعات أمواج؟",
                "نعم — موقعنا مناسب للمقيمين حول بوابة أمواج 1 وكمبوندات الساحل المجاورة.",
            ),
        ],
        "links": [("/emergency-vet-north-coast", "Emergency 24/7"), ("/contact-directions-booking", "Directions")],
    },
    {
        "url": "/veterinary-home-visits-sahel",
        "name": "Veterinary Home Visits Sahel",
        "title": "Veterinary Home Visits in El Sahel | PetSpot",
        "meta": "Veterinary home visits for North Coast compounds when suitable. Book via WhatsApp 01000059085.",
        "h1_en": "Veterinary home visits in El Sahel",
        "h1_ar": "زيارات بيطرية منزلية في الساحل",
        "body_en": (
            "When travel is difficult for your pet, ask about a home visit to your North Coast compound. "
            "Availability depends on clinical need and schedule. Emergencies may still require clinic care — call us for guidance."
        ),
        "body_ar": (
            "عندما يصعب نقل أليفك، اسألوا عن زيارة منزلية لكمبوندكم في الساحل. التوفر يعتمد على الحالة والجدول. "
            "بعض الطوارئ قد تحتاج الحضور للعيادة — اتصلوا للإرشاد."
        ),
        "faqs": [
            (
                "Clinic visit or home visit?",
                "Stable wellness cases may suit a home visit. Critical emergencies usually need the clinic. Message WhatsApp with a short description.",
                "عيادة أم زيارة منزلية؟",
                "حالات الاستقرار قد تناسب الزيارة المنزلية. الطوارئ الحرجة غالبًا تحتاج العيادة. راسلوا واتساب بوصف مختصر.",
            ),
        ],
        "links": [("/emergency-vet-north-coast", "Emergency"), ("/blog", "Articles")],
    },
    {
        "url": "/pet-vaccinations-north-coast",
        "name": "Pet Vaccinations North Coast",
        "title": "Pet Vaccinations North Coast | PetSpot El Sahel",
        "meta": "Pet vaccination visits on Egypt's North Coast near Amwaj Gate 1. Book WhatsApp 01000059085.",
        "h1_en": "Pet vaccinations on the North Coast",
        "h1_ar": "تطعيمات الحيوانات الأليفة في الساحل الشمالي",
        "body_en": (
            "Keep vaccination schedules current before travel and during summer stays. Our team advises on core vaccines "
            "based on your pet's history — we do not invent vaccine brands or outcomes on this page. Bring prior records if available."
        ),
        "body_ar": (
            "حافظوا على مواعيد التطعيم قبل السفر وأثناء المصيف. نرشدكم حسب تاريخ أليفك — لا نذكر علامات تجارية أو نتائج غير موثقة هنا. أحضروا السجلات إن وُجدت."
        ),
        "faqs": [
            (
                "Should I vaccinate before the coast trip?",
                "Ask us with your pet's age and last vaccine dates. Early planning reduces summer risks.",
                "هل أطعّم قبل السفر للساحل؟",
                "اسألونا مع عمر أليفك وآخر تطعيم. التخطيط المبكر يقلل مخاطر الصيف.",
            ),
        ],
        "links": [("/veterinary-clinic-near-amwaj", "Visit the clinic"), ("/blog", "Summer safety articles")],
    },
    {
        "url": "/grooming-boarding-sahel",
        "name": "Grooming and Boarding Sahel",
        "title": "Pet Grooming & Boarding El Sahel | PetSpot",
        "meta": "Pet grooming and boarding near Amwaj Gate 1 on the North Coast. WhatsApp 01000059085.",
        "h1_en": "Grooming and boarding in El Sahel",
        "h1_ar": "جروومينج وبوردينج في الساحل",
        "body_en": (
            "Summer heat and beach living can stress coats and routines. PetSpot offers professional grooming and supervised boarding. "
            "Share your pet's temperament and any medical notes when booking. Prices are confirmed with the clinic — we do not list unverified rates here."
        ),
        "body_ar": (
            "حر الصيف والحياة على الشاطئ قد ترهق فرو أليفك وروتينه. نوفر جرومينج احترافي وبوردينج تحت الإشراف. "
            "اذكروا طبع أليفك وأي ملاحظات طبية عند الحجز. الأسعار تُؤكد مع العيادة — لا نعرض أسعارًا غير موثقة هنا."
        ),
        "faqs": [
            (
                "Can boarding pets get grooming too?",
                "Often yes — ask when you book so we can plan staff time.",
                "هل يمكن الجمع بين البوردينج والجرومينج؟",
                "غالبًا نعم — اسألوا عند الحجز لتنظيم الوقت.",
            ),
        ],
        "links": [("/contact-directions-booking", "Book"), ("/blog", "Parasite & summer tips")],
    },
    {
        "url": "/contact-directions-booking",
        "name": "Contact Directions Booking",
        "title": "Contact, Directions & Booking | PetSpot El Sahel",
        "meta": "Contact PetSpot El Sahel: clinic 01280833332, call center 01201568888, WhatsApp 01000059085. Directions near Amwaj Gate 1.",
        "h1_en": "Contact, directions and booking",
        "h1_ar": "تواصل واتجاهات وحجز",
        "body_en": (
            "Use the clinic line for on-site needs, the call center for routing, and WhatsApp for quick booking messages. "
            "Directions open the verified Google Maps pin beside Amwaj Gate 1 on the Main Road."
        ),
        "body_ar": (
            "استخدموا هاتف العيادة للاحتياجات الميدانية، ومركز الاتصال للتوجيه، وواتساب للحجز السريع. "
            "الاتجاهات تفتح موقع خرائط جوجل الموثق بجوار بوابة أمواج 1 على الطريق الرئيسي."
        ),
        "faqs": [],
        "links": [("/appointment", "Appointment types"), ("/blog", "Pet care guide")],
    },
]


def build_service_page_arch(c: dict[str, Any], page: dict[str, Any]) -> str:
    faqs = page.get("faqs") or []
    faq_block = _faq_html(faqs) if faqs else ""
    ld_objs = [veterinary_care_ld(c, c["website_url"].rstrip("/") + page["url"])]
    if faqs:
        ld_objs.append(faq_ld([(q, a) for q, a, _, _ in faqs]))
    ld = script_tag(*ld_objs)
    links = "".join(
        f'<li><a href="{href}">{label}</a></li>' for href, label in page.get("links") or []
    )
    return f"""<t name="{page["name"]}" t-name="website.petspot_page_{page["url"].strip("/").replace("-", "_")}">
  <t t-call="website.layout">
    <div id="wrap" class="oe_structure">
      {ld}
      <section class="s_title pt48 pb24">
        <div class="container">
          <h1>{page["h1_en"]}</h1>
          <h2 dir="rtl" class="h4">{page["h1_ar"]}</h2>
          <p class="text-muted">{c["company_name"]} · {c["area_en"]}</p>
        </div>
      </section>
      <section class="s_text_block pb32">
        <div class="container">
          <div class="row">
            <div class="col-lg-8">
              <p class="lead">{page["body_en"]}</p>
              <p dir="rtl" class="lead">{page["body_ar"]}</p>
              <p class="small text-muted"><strong>Medical note:</strong> Online content cannot replace an examination.
                For emergencies contact the clinic immediately.</p>
              <p dir="rtl" class="small text-muted"><strong>تنويه طبي:</strong> المحتوى الإلكتروني لا يغني عن الفحص.
                للطوارئ تواصلوا مع العيادة فورًا.</p>
              {_contact_block(c)}
              {_cta_row(c)}
              {('<div class="mt-5"><h2 class="h4">FAQ</h2>' + faq_block + "</div>") if faq_block else ""}
              <div class="mt-4">
                <h2 class="h5">Related</h2>
                <ul>{links}<li><a href="/">Home</a></li></ul>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </t>
</t>"""
