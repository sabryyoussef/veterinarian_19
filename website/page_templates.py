"""Odoo website QWeb arch templates for PetSpot El Sahel."""
from __future__ import annotations

from typing import Any


def _service_card_style(svc: dict[str, Any], gallery_urls: dict[str, str]) -> str:
    color = svc.get("color", "#1a5f7a")
    slot_id = svc.get("gallery_slot")
    image_url = gallery_urls.get(slot_id) if slot_id else None
    if image_url:
        return (
            f"background: linear-gradient(165deg, {color}e6 0%, {color}bf 55%, {color}99 100%), "
            f"url('{image_url}') center/cover no-repeat;"
        )
    return (
        f"background: linear-gradient(165deg, {color} 0%, {color}dd 45%, {color}bb 100%);"
    )


def _service_cards(c: dict[str, Any]) -> str:
    rows = []
    wa = c["whatsapp_url"]
    phone_tel = c["phone_tel"]
    gallery_urls = c.get("gallery_urls") or {}
    for svc in c["services"]:
        cta_href = wa if svc.get("id") != "pet_supplies" else f"tel:{phone_tel}"
        icon = svc.get("icon", "fa-paw")
        style = _service_card_style(svc, gallery_urls)
        rows.append(
            f"""<div class="col-md-6 col-lg-4">
  <div class="card h-100 border-0 shadow-sm overflow-hidden">
    <div class="card-body d-flex flex-column text-white p-4"
         style="min-height:300px; {style}">
      <div class="mb-3 opacity-75"><i class="fa {icon} fa-2x"/></div>
      <h5 class="fw-bold mb-1">{svc["title_en"]}</h5>
      <p dir="rtl" class="small mb-2 opacity-90">{svc["title_ar"]}</p>
      <p class="small mb-2 opacity-90">{svc["desc_en"]}</p>
      <p dir="rtl" class="small mb-3 opacity-90">{svc["desc_ar"]}</p>
      <a class="btn btn-light btn-sm mt-auto align-self-start" href="{cta_href}" target="_blank" rel="noopener">
        {svc.get("cta_en", "Book on WhatsApp")}
      </a>
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

    logo_url = c.get("logo_url", "/web/image/res.company/1/logo")
    hero_url = c.get("hero_image_url", "")
    grooming_url = (c.get("gallery_urls") or {}).get("grooming", "")
    clinic_front_url = (c.get("gallery_urls") or {}).get("clinic_front", "")
    hero_col = ""
    if hero_url:
        hero_col = f"""<div class="col-lg-6 order-lg-2 text-center">
              <div class="p-2 p-lg-0">
                <img src="{hero_url}" alt="{b["name_en"]} — veterinary clinic on the North Coast"
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

    return f"""<t name="Homepage" t-name="website.homepage">
  <t t-call="website.layout" pageName.f="homepage">
    <div id="wrap" class="oe_structure">
      <!-- PetSpot El Sahel marketing homepage — see website/business_data.json -->
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
              <div class="d-grid gap-2" style="max-width:420px;">
                <a class="btn btn-success btn-lg" href="{wa}" target="_blank" rel="noopener">
                  <i class="fa fa-whatsapp me-2"/> Book on WhatsApp
                  <span class="mx-1">·</span>
                  <span dir="rtl">احجز على واتساب</span>
                </a>
                <div class="row g-2">
                  <div class="col-6">
                    <a class="btn btn-light w-100" href="{maps}" target="_blank" rel="noopener">
                      <i class="fa fa-map-marker me-1"/> Directions
                    </a>
                  </div>
                  <div class="col-6">
                    <a class="btn btn-outline-light w-100" href="tel:{phone_tel}">
                      <i class="fa fa-phone me-1"/> Call
                    </a>
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
            <div class="col-md-3"><div class="p-3"><i class="fa fa-user-md fa-2x text-primary mb-2"/><h5>Experienced team</h5><p class="text-muted">Trusted vets for cats, dogs &amp; exotics.</p><p dir="rtl" class="mb-0 small">فريق بيطري خبير.</p></div></div>
            <div class="col-md-3"><div class="p-3"><i class="fa fa-map-marker fa-2x text-primary mb-2"/><h5>Amwaj 1 location</h5><p class="text-muted">Beside Amwaj 1 gate on the main road.</p><p dir="rtl" class="mb-0 small">بجوار بوابة أمواج 1 على الطريق الرئيسي.</p></div></div>
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
              {(
                f'<img src="{grooming_url}" alt="PetSpot grooming and boarding area" '
                f'class="img-fluid rounded shadow-sm w-100" style="max-height:360px; object-fit:cover;"/>'
                if grooming_url
                else '<div class="border rounded bg-light p-5 text-center text-muted"><i class="fa fa-paw fa-3x mb-3"/><p class="small">PetSpot grooming &amp; boarding area</p></div>'
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
            <p class="text-muted small">Real photos from our clinic and Facebook page</p>
          </div>
          <div class="row g-3">
            {_gallery_items(c)}
          </div>
        </div>
      </section>

      <section class="s_text_block pt64 pb64 bg-200" data-snippet="s_text_block" data-name="About">
        <div class="container">
          <div class="row align-items-center g-4">
            <div class="col-lg-6">
              <h2>About {c["company_name"]}</h2>
              <h3 dir="rtl" class="h4 mb-3">{b["name_ar"]}</h3>
              <p class="lead">{b["legal_name"] if b.get("legal_name") else b["name_en"]} — {b["subheadline_en"]}</p>
              <p dir="rtl" class="lead">{b["subheadline_ar"]}</p>
              <p>{b["positioning_en"]}</p>
              <p dir="rtl">{b["positioning_ar"]}</p>
              <p class="mb-0"><strong>{c["address_en"]}</strong></p>
              <p dir="rtl" class="mb-0"><strong>{c["address_ar"]}</strong></p>
            </div>
            <div class="col-lg-6 text-center">
              {about_image}
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
              <p><strong>Address:</strong> {c["address_en"]}</p>
              <p dir="rtl"><strong>العنوان:</strong> {c["address_ar"]}</p>
              <p><strong>Area:</strong> {c["area_en"]}</p>
              <p dir="rtl"><strong>المنطقة:</strong> {c["area_ar"]}</p>
              <p><strong>Hours:</strong> {c["hours_en"]}</p>
              <p dir="rtl"><strong>المواعيد:</strong> {c["hours_ar"]}</p>
              <p><strong>Phone:</strong> <a href="tel:{phone_tel}">{phone}</a></p>
              {marassi_block}
              <div class="d-flex flex-wrap gap-2 mt-3">
                <a class="btn btn-primary" href="{maps}" target="_blank" rel="noopener">Get Directions / افتح الموقع</a>
                <a class="btn btn-success" href="{wa}" target="_blank" rel="noopener">WhatsApp</a>
                <a class="btn btn-outline-primary" href="tel:{phone_tel}">Call now</a>
              </div>
            </div>
            <div class="col-lg-7">
              <div class="border rounded bg-light p-5 text-center" style="min-height:280px;">
                <i class="fa fa-map-marker fa-3x text-primary mb-3"/>
                <p class="lead mb-2">{c["address_en"]}</p>
                <p dir="rtl" class="mb-4">{c["address_ar"]}</p>
                <a class="btn btn-primary btn-lg" href="{maps}" target="_blank" rel="noopener">
                  Open in Google Maps
                </a>
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
          <p>{c["address_en"]}</p>
          <p dir="rtl">{c["address_ar"]}</p>
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


def build_footer_inherit_arch(c: dict[str, Any]) -> str:
    """QWeb inherit arch replacing Odoo default footer with PetSpot data."""
    b = c["brand"]
    phone = c["phone"]
    phone_tel = c["phone_tel"]
    alt = c.get("phone_alternate", "")
    alt_line = ""
    if alt:
        alt_tel = alt.replace(" ", "")
        alt_line = (
            f'<li><i class="fa fa-phone fa-fw me-2"/>'
            f'<a href="tel:{alt_tel}"><span class="o_force_ltr">{alt}</span></a></li>'
        )
    return f"""<data>
  <xpath expr="//div[@id='footer']" position="replace">
    <div id="footer" class="oe_structure oe_structure_solo border text-break" t-ignore="true" t-if="not no_footer"
         style="--box-border-left-width: 0px; --box-border-right-width: 0px;">
      <section class="s_text_block pt40 pb16" data-snippet="s_text_block" data-name="PetSpot Footer">
        <div class="container">
          <div class="row">
            <div class="col-lg-3 pt24 pb24">
              <h5>Useful Links</h5>
              <ul class="list-unstyled">
                <li><a href="/">Home</a></li>
                <li><a href="/#services">Services</a></li>
                <li><a href="/#gallery">Gallery</a></li>
                <li><a href="/#location">Location</a></li>
                <li><a href="/contactus">Contact us</a></li>
              </ul>
            </div>
            <div class="col-lg-5 pt24 pb24">
              <h5>About {c["company_name"]}</h5>
              <p>{b["positioning_en"]}</p>
              <p dir="rtl">{b["positioning_ar"]}</p>
              <p class="mb-0"><strong>{c["address_en"]}</strong></p>
              <p dir="rtl" class="mb-0"><strong>{c["address_ar"]}</strong></p>
              <p class="text-muted small mt-2 mb-0">{c["hours_en"]} · {c["hours_ar"]}</p>
            </div>
            <div class="col-lg-4 pt24 pb24">
              <h5>Connect with us</h5>
              <ul class="list-unstyled">
                <li><i class="fa fa-comment fa-fw me-2"/><a href="/contactus">Contact us</a></li>
                <li><i class="fa fa-envelope fa-fw me-2"/><a href="mailto:{c["email"]}">{c["email"]}</a></li>
                <li><i class="fa fa-phone fa-fw me-2"/><a href="tel:{phone_tel}"><span class="o_force_ltr">{phone}</span></a></li>
                {alt_line}
                <li><i class="fa fa-whatsapp fa-fw me-2"/><a href="{c["whatsapp_url"]}" target="_blank" rel="noopener">WhatsApp</a></li>
                <li><i class="fa fa-map-marker fa-fw me-2"/><a href="{c["maps_url"]}" target="_blank" rel="noopener">Google Maps</a></li>
              </ul>
              <div class="s_social_media text-start o_not_editable" data-snippet="s_social_media" data-name="Social Media" contenteditable="false">
                <h5 class="s_social_media_title d-none">Follow us</h5>
                <a href="{c["facebook"]}" class="s_social_media_facebook" target="_blank" rel="noopener" aria-label="Facebook">
                  <i class="fa fa-facebook rounded-circle shadow-sm o_editable_media"/>
                </a>
                <a href="{c["instagram"]}" class="s_social_media_instagram" target="_blank" rel="noopener" aria-label="Instagram">
                  <i class="fa fa-instagram rounded-circle shadow-sm o_editable_media"/>
                </a>
                <a href="{c["whatsapp_url"]}" class="s_social_media_whatsapp" target="_blank" rel="noopener" aria-label="WhatsApp">
                  <i class="fa fa-whatsapp rounded-circle shadow-sm o_editable_media"/>
                </a>
              </div>
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
