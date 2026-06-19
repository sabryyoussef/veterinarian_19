"""Odoo website QWeb arch templates for PetSpot El Sahel."""
from __future__ import annotations

from typing import Any


def _service_cards(c: dict[str, Any]) -> str:
    rows = []
    wa = c["whatsapp_url"]
    phone_tel = c["phone_tel"]
    for svc in c["services"]:
        price = ""
        if svc.get("price_egp"):
            price = f'<p class="text-primary fw-semibold mb-2">{svc["price_egp"]:,} EGP</p>'
        elif svc.get("price_note_en"):
            price = (
                f'<p class="text-primary fw-semibold mb-2">{svc["price_note_en"]}</p>'
                f'<p dir="rtl" class="text-primary small mb-2">{svc.get("price_note_ar", "")}</p>'
            )
        cta_href = wa if svc.get("id") != "pet_supplies" else f"tel:{phone_tel}"
        rows.append(
            f"""<div class="col-md-6 col-lg-4">
  <div class="card h-100 shadow-sm border-0 p-4">
    <h5>{svc["title_en"]}</h5>
    <p dir="rtl" class="text-muted small mb-2">{svc["title_ar"]}</p>
    <p class="text-muted">{svc["desc_en"]}</p>
    <p dir="rtl" class="text-muted">{svc["desc_ar"]}</p>
    {price}
    <a class="btn btn-outline-primary btn-sm mt-auto" href="{cta_href}" target="_blank" rel="noopener">
      {svc.get("cta_en", "Book on WhatsApp")}
    </a>
  </div>
</div>"""
        )
    return "\n".join(rows)


def _gallery_items(c: dict[str, Any]) -> str:
    items = []
    for slot in c["gallery_slots"]:
        items.append(
            f"""<div class="col-md-6 col-lg-3">
  <div class="border rounded bg-light d-flex align-items-center justify-content-center text-center p-4"
       style="min-height:200px;" role="img" aria-label="{slot["alt"]}">
    <div>
      <i class="fa fa-camera fa-2x text-muted mb-2"/>
      <p class="small text-muted mb-0">{slot["alt"]}</p>
      <p class="small text-muted mb-0"><!-- TODO: add {slot["file"]} to website/assets/gallery/ --></p>
    </div>
  </div>
</div>"""
        )
    return "\n".join(items)


def build_homepage_arch(c: dict[str, Any]) -> str:
    b = c["brand"]
    phone = c["phone"]
    phone_tel = c["phone_tel"]
    wa = c["whatsapp_url"]
    maps = c["maps_url"]
    fb = c["facebook"]
    ig = c["instagram"]
    marassi = c.get("phone_marassi", "")
    marassi_block = ""
    if marassi:
        marassi_tel = marassi.replace(" ", "")
        marassi_block = (
            f'<p><strong>Marassi line:</strong> '
            f'<a href="tel:{marassi_tel}">{marassi}</a></p>'
        )

    return f"""<t name="Homepage" t-name="website.homepage">
  <t t-call="website.layout" pageName.f="homepage">
    <div id="wrap" class="oe_structure">
      <!-- PetSpot El Sahel marketing homepage — see website/business_data.json -->
      <section class="s_cover pt96 pb96 o_colored_level" data-snippet="s_cover" data-name="Hero"
               style="background: linear-gradient(135deg, #1a5f7a 0%, #2d8f6f 100%);">
        <div class="container">
          <div class="row align-items-center">
            <div class="col-lg-8 pt32 pb32">
              <h1 class="display-4 fw-bold text-white">{b["tagline_en"]}</h1>
              <h2 class="h3 text-white mb-3" dir="rtl">{b["tagline_ar"]}</h2>
              <p class="lead text-white">{b["subheadline_en"]}</p>
              <p class="lead text-white" dir="rtl">{b["subheadline_ar"]}</p>
              <div class="mt-4 d-flex flex-wrap gap-3">
                <a class="btn btn-success btn-lg" href="{wa}" target="_blank" rel="noopener">
                  <i class="fa fa-whatsapp me-2"/> Book on WhatsApp / احجز على واتساب
                </a>
                <a class="btn btn-light btn-lg" href="{maps}" target="_blank" rel="noopener">
                  <i class="fa fa-map-marker me-2"/> Get Directions / افتح الموقع
                </a>
                <a class="btn btn-outline-light btn-lg" href="tel:{phone_tel}">
                  <i class="fa fa-phone me-2"/> Call / اتصل
                </a>
              </div>
            </div>
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
            <div class="col-md-3"><div class="p-3"><i class="fa fa-user-md fa-2x text-primary mb-2"/><h5>Experienced team</h5><p class="text-muted">Trusted vets for cats, dogs &amp; exotics.</p><p dir="rtl" class="mb-0 small">فريق بيطري خبير.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-map-marker fa-2x text-primary mb-2"/><h5>El Sahel location</h5><p class="text-muted">Convenient North Coast care.</p><p dir="rtl" class="mb-0 small">موقع مميز على الساحل.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-sun-o fa-2x text-primary mb-2"/><h5>Seasonal pet care</h5><p class="text-muted">Full services all summer long.</p><p dir="rtl" class="mb-0 small">رعاية طوال موسم الصيف.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-whatsapp fa-2x text-success mb-2"/><h5>Easy WhatsApp booking</h5><p class="text-muted">Book in seconds from your phone.</p><p dir="rtl" class="mb-0 small">حجز سريع عبر واتساب.</p></div></div>
          </div>
        </div>
      </section>

      <section id="services" class="s_three_columns pt64 pb64 bg-200" data-snippet="s_three_columns" data-name="Services">
        <div class="container">
          <div class="text-center mb-5">
            <h2>Our Services</h2>
            <h3 dir="rtl" class="h4">خدماتنا</h3>
            <p class="text-muted">Veterinary clinic, grooming, boarding, vaccination &amp; home visits</p>
          </div>
          <div class="row g-4">
            {_service_cards(c)}
          </div>
        </div>
      </section>

      <section class="s_text_block pt64 pb64" style="background-color:#fff8f5;" data-snippet="s_text_block" data-name="Boarding Grooming">
        <div class="container">
          <div class="row g-4 align-items-center">
            <div class="col-lg-6">
              <h2>Grooming &amp; Boarding</h2>
              <h3 dir="rtl" class="h4">الجروومينج والبوردينج</h3>
              <p>Professional grooming keeps your pet comfortable in the summer heat. Our boarding area offers a safe, supervised stay while you enjoy the North Coast — daily or hourly options available.</p>
              <p dir="rtl">جرومينج احترافي لراحة أليفك في حر الصيف. منطقة البوردينج توفر إقامة آمنة تحت الإشراف أثناء استمتاعكم بالساحل — خيارات يومية أو بالساعة.</p>
              <a class="btn btn-primary me-2" href="{wa}" target="_blank" rel="noopener">Book grooming / احجز جروومينج</a>
              <a class="btn btn-outline-primary" href="{wa}" target="_blank" rel="noopener">Book boarding / احجز بوردينج</a>
            </div>
            <div class="col-lg-6">
              <div class="border rounded bg-light p-5 text-center text-muted">
                <i class="fa fa-paw fa-3x mb-3"/>
                <p class="mb-0"><!-- TODO: PetSpot grooming area photo — assets/gallery/grooming-area.jpg --></p>
                <p class="small">PetSpot grooming &amp; boarding area</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="gallery" class="s_images_wall pt64 pb64" data-snippet="s_images_wall" data-name="Gallery">
        <div class="container">
          <div class="text-center mb-5">
            <h2>Clinic Gallery</h2>
            <h3 dir="rtl" class="h4">معرض العيادة</h3>
            <p class="text-muted small">Real photos coming soon — add images to <code>website/assets/gallery/</code></p>
          </div>
          <div class="row g-3">
            {_gallery_items(c)}
          </div>
        </div>
      </section>

      <section class="s_text_block pt64 pb64 bg-200" data-snippet="s_text_block" data-name="About">
        <div class="container">
          <div class="row align-items-center">
            <div class="col-lg-6">
              <h2>About {c["company_name"]}</h2>
              <p>{b["positioning_en"]}</p>
              <p dir="rtl">{b["positioning_ar"]}</p>
            </div>
            <div class="col-lg-6 text-center">
              <div class="border rounded bg-light p-5 text-muted">
                <i class="fa fa-hospital-o fa-3x mb-3"/>
                <p class="small mb-0"><!-- TODO: PetSpot El Sahel clinic front — assets/gallery/clinic-front.jpg --></p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="location" class="s_text_block pt64 pb64" style="background-color:#fff8f5;" data-snippet="s_text_block" data-name="Location">
        <div class="container">
          <div class="text-center mb-4">
            <h2>Find us on the North Coast</h2>
            <h3 dir="rtl" class="h4">موقعنا على الساحل الشمالي</h3>
          </div>
          <div class="row g-4">
            <div class="col-lg-5">
              <p><strong>Area:</strong> {c["area_en"]}</p>
              <p dir="rtl"><strong>المنطقة:</strong> {c["area_ar"]}</p>
              <p class="small text-muted"><!-- TODO: {c["address_note"]} --></p>
              <p><strong>Hours:</strong> {c["hours_en"]}</p>
              <p dir="rtl"><strong>المواعيد:</strong> {c["hours_ar"]}</p>
              <p><strong>Phone:</strong> <a href="tel:{phone_tel}">{phone}</a></p>
              {marassi_block}
              <div class="d-flex flex-wrap gap-2 mt-3">
                <a class="btn btn-primary" href="{maps}" target="_blank" rel="noopener">Google Maps</a>
                <a class="btn btn-success" href="{wa}" target="_blank" rel="noopener">WhatsApp</a>
                <a class="btn btn-outline-primary" href="tel:{phone_tel}">Call now</a>
              </div>
            </div>
            <div class="col-lg-7">
              <div class="border rounded bg-light p-5 text-center text-muted" style="min-height:280px;">
                <i class="fa fa-map fa-3x mb-3"/>
                <p><a href="{maps}" target="_blank" rel="noopener">Open location in Google Maps</a></p>
                <p class="small mb-0">Map embed pending exact address confirmation</p>
              </div>
            </div>
          </div>
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
          <p class="mt-4 mb-0"><a href="/contactus">Contact form</a> · <a href="mailto:{c["email"]}">{c["email"]}</a></p>
        </div>
      </section>
    </div>
  </t>
</t>"""


def build_contact_arch(c: dict[str, Any]) -> str:
    phone = c["phone"]
    phone_tel = c["phone_tel"]
    wa = c["whatsapp_url"]
    maps = c["maps_url"]
    fb = c["facebook"]
    b = c["brand"]
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
      <section class="s_title pt48 pb24" data-snippet="s_title">
        <div class="container text-center">
          <h1>Contact Us</h1>
          <h2 dir="rtl" class="h4">تواصل معنا</h2>
          <p class="lead">{c["company_name"]} — North Coast veterinary &amp; pet care</p>
          <p dir="rtl" class="lead">{b["name_ar"]} — رعاية بيطرية على الساحل الشمالي</p>
        </div>
      </section>
      <section class="s_text_block pb24" data-snippet="s_text_block">
        <div class="container text-center">
          <p><strong>Phone:</strong> <a href="tel:{phone_tel}">{phone}</a></p>
          <p><strong>WhatsApp:</strong> <a href="{wa}" target="_blank" rel="noopener">{c["whatsapp"]}</a></p>
          <p><strong>Email:</strong> <a href="mailto:{c["email"]}">{c["email"]}</a></p>
          <p>{c["area_en"]}</p>
          <p dir="rtl">{c["area_ar"]}</p>
          <p class="mt-3">
            <a class="btn btn-primary me-2" href="{maps}" target="_blank" rel="noopener">Google Maps</a>
            <a class="btn btn-outline-primary" href="{fb}" target="_blank" rel="noopener">Facebook</a>
          </p>
        </div>
      </section>
      <section class="s_website_form pt24 pb64" data-snippet="s_website_form">
        <div class="container">
          <div class="row">
            <div class="col-lg-8 offset-lg-2">
              <form id="contactus_form" action="/website/form/" method="post" enctype="multipart/form-data" class="o_mark_required" data-mark="*" data-model_name="mail.mail" data-success-mode="redirect" data-success-page="/contactus-thank-you" data-pre-fill="true">
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
