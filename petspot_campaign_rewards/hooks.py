# -*- coding: utf-8 -*-
import logging
import re

_logger = logging.getLogger(__name__)

CONTACT_ROLES = {"name", "phone", "email", "pet_type"}
CHAR_PLACEHOLDERS = {
    "name": "e.g. Mohamed Ali",
    "phone": "01xxxxxxxxx (WhatsApp)",
    "email": "name@example.com (optional)",
    "pet_type": "Dog / Cat / Other",
}
YES_NO_LABELS = [("Yes | نعم", True), ("No | لا", False)]
TRUE_FALSE_LABELS = [("True | صح", True), ("False | خطأ", False)]

EPISODES = [
    {
        "sequence": 10,
        "title": "Summer Heat Safety",
        "title_ar": "السلامة في حرارة الصيف",
        "content_type": "combined",
        "issue_reward": False,
        "reward_discount_percent": 0,
        "article_html": """
<h2>Summer heat safety for pets | السلامة في حر الصيف</h2>
<p>Never leave pets in parked cars. Offer fresh water and shade on the North Coast.</p>
<p>لا تترك أليفك داخل السيارة. وفّر ماءً ظلاً في الساحل.</p>
<ul>
<li>Watch for panting, drooling, weakness — signs of heatstroke.</li>
<li>Amwaj 1 clinic: beside Amwaj 1 gate, Sidi Abdel Rahman.</li>
</ul>
""",
        "slide_html": "<p>Quick guide: keep walks early morning or after sunset at the North Coast.</p>",
        "fb_teaser": "🌞 Episode 1 — Summer heat safety for your pet on the North Coast!\nLearn the signs of heatstroke and how PetSpot El Sahel can help.\n\n🐾 بيت سبوت الساحل",
        "quiz_title": "Summer Heat Safety Quiz",
        "quiz_questions": [
            ("Should you leave a dog in a parked car in summer?", "simple_choice", [("Yes | نعم", False), ("No | لا", True)]),
            ("Fresh water and shade help prevent heatstroke.", "simple_choice", TRUE_FALSE_LABELS),
            ("Panting and weakness can signal heatstroke.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot El Sahel is located at Amwaj 1, North Coast.", "simple_choice", TRUE_FALSE_LABELS),
            ("You should walk pets at midday in peak summer heat.", "simple_choice", [("Yes | نعم", False), ("No — morning/evening | لا — صباحاً/مساءً", True)]),
        ],
    },
    {
        "sequence": 20,
        "title": "Vaccination Before Travel",
        "title_ar": "التطعيمات قبل السفر",
        "content_type": "combined",
        "issue_reward": False,
        "reward_discount_percent": 0,
        "article_html": """
<h2>Vaccinations before vacation | التطعيمات قبل الإجازة</h2>
<p>Update core vaccines before traveling to the North Coast with your pet.</p>
<p>حدّث تطعيمات أليفك قبل السفر إلى الساحل.</p>
""",
        "slide_html": "<p>Book a pre-travel check at PetSpot — vaccinations, health certificate advice.</p>",
        "fb_teaser": "💉 Episode 2 — Vaccinate before you travel to the Sahel with your pet!",
        "quiz_title": "Vaccination Quiz",
        "quiz_questions": [
            ("Vaccinations help protect pets during vacation.", "simple_choice", TRUE_FALSE_LABELS),
            ("You should skip vaccines if the pet looks healthy.", "simple_choice", [("True | صح", False), ("False | خطأ", True)]),
            ("PetSpot offers vaccination services.", "simple_choice", TRUE_FALSE_LABELS),
            ("Core vaccines should be updated before travel.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot Amwaj 1 phone number:", "char_box", [], "phone"),
        ],
    },
    {
        "sequence": 30,
        "title": "Grooming Summer Care",
        "title_ar": "الجروومينج في الصيف",
        "content_type": "combined",
        "issue_reward": False,
        "reward_discount_percent": 0,
        "article_html": "<h2>Summer grooming</h2><p>Professional grooming keeps coats healthy in humid coastal weather.</p>",
        "slide_html": "<p>Grooming services at PetSpot El Sahel — fresh summer look for dogs and cats.</p>",
        "fb_teaser": "✨ Episode 3 — Summer grooming tips at PetSpot El Sahel!",
        "quiz_title": "Grooming Quiz",
        "quiz_questions": [
            ("Grooming helps skin and coat health in summer.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot offers professional grooming.", "simple_choice", TRUE_FALSE_LABELS),
            ("You never need grooming in short-haired breeds.", "simple_choice", [("True | صح", False), ("False | خطأ", True)]),
            ("Humidity on the North Coast can affect coat care.", "simple_choice", TRUE_FALSE_LABELS),
            ("Your WhatsApp number for grooming booking:", "char_box", [], "phone"),
        ],
    },
    {
        "sequence": 40,
        "title": "Boarding Checklist",
        "title_ar": "قائمة البوردينج",
        "content_type": "combined",
        "issue_reward": False,
        "reward_discount_percent": 0,
        "article_html": "<h2>Boarding checklist</h2><p>Pack vaccination record, favorite food, and emergency contact.</p>",
        "slide_html": "<p>Safe supervised boarding while you enjoy the coast.</p>",
        "fb_teaser": "🏠 Episode 4 — Boarding checklist for a worry-free Sahel vacation!",
        "quiz_title": "Boarding Checklist Survey",
        "quiz_questions": [
            ("Vaccination records are useful for boarding.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot offers boarding on the North Coast.", "simple_choice", TRUE_FALSE_LABELS),
            ("You should pack your pet's regular food.", "simple_choice", TRUE_FALSE_LABELS),
            ("Emergency contact details are important.", "simple_choice", TRUE_FALSE_LABELS),
        ],
    },
    {
        "sequence": 50,
        "title": "Pet Nutrition Basics",
        "title_ar": "أساسيات التغذية",
        "content_type": "combined",
        "issue_reward": False,
        "reward_discount_percent": 0,
        "article_html": "<h2>Nutrition basics</h2><p>Balanced diet and fresh water — especially active summer days.</p>",
        "slide_html": "<p>Ask our vets about nutrition during your next visit.</p>",
        "fb_teaser": "🍽 Episode 5 — Pet nutrition basics for an active Sahel summer!",
        "quiz_title": "Nutrition Quiz",
        "quiz_questions": [
            ("Fresh water should always be available.", "simple_choice", TRUE_FALSE_LABELS),
            ("Sudden diet changes are always safe.", "simple_choice", [("True | صح", False), ("False | خطأ", True)]),
            ("Active pets may need adjusted feeding routines.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot vets can advise on nutrition.", "simple_choice", TRUE_FALSE_LABELS),
            ("Human chocolate is safe for dogs.", "simple_choice", [("True | صح", False), ("False | خطأ", True)]),
            ("Cats need hydration in hot weather.", "simple_choice", TRUE_FALSE_LABELS),
            ("Table scraps are the best summer diet.", "simple_choice", [("True | صح", False), ("False | خطأ", True)]),
            ("Quality food supports immunity.", "simple_choice", TRUE_FALSE_LABELS),
        ],
    },
    {
        "sequence": 60,
        "title": "Grand Quiz — Win 10% Off",
        "title_ar": "الاختبار الكبير — خصم 10%",
        "content_type": "survey",
        "issue_reward": True,
        "reward_discount_percent": 10,
        "article_html": "<h2>Grand quiz recap</h2><p>Review heat safety, vaccines, grooming, boarding, and nutrition — then take the grand quiz!</p>",
        "slide_html": "<p>Complete the grand quiz with 80%+ to receive your 10% clinic discount code.</p>",
        "fb_teaser": "🎁 Episode 6 — Grand Quiz! Pass and win 10% off at PetSpot El Sahel!\n🐾 أكمل الاختبار واربح خصم 10%",
        "quiz_title": "PetSpot Grand Summer Quiz",
        "quiz_questions": [
            ("Your name | الاسم", "char_box", [], "name"),
            ("WhatsApp / Phone | رقم الموبايل", "char_box", [], "phone"),
            ("Email (optional) | البريد", "char_box", [], "email"),
            ("Heatstroke can be fatal without quick action.", "simple_choice", TRUE_FALSE_LABELS),
            ("Vaccinations should be considered before travel.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot offers grooming and boarding.", "simple_choice", TRUE_FALSE_LABELS),
            ("Amwaj 1 branch phone is 01201568888.", "simple_choice", TRUE_FALSE_LABELS),
            ("Marsa Matruh branch phone is 01280833332.", "simple_choice", TRUE_FALSE_LABELS),
            ("Fresh water prevents dehydration in summer.", "simple_choice", TRUE_FALSE_LABELS),
            ("PetSpot is located on Egypt's North Coast.", "simple_choice", TRUE_FALSE_LABELS),
        ],
    },
    {
        "sequence": 70,
        "title": "Bonus Gift — 15% Off",
        "title_ar": "هدية إضافية — خصم 15%",
        "content_type": "survey",
        "issue_reward": True,
        "reward_discount_percent": 15,
        "article_html": "<h2>Bonus gift survey</h2><p>Tell us about your pet and receive 15% off!</p>",
        "slide_html": "",
        "fb_teaser": "🎉 Final Episode — Share & win 15% off at PetSpot El Sahel!\nاملأ الاستبيان واحصل على كود الخصم",
        "quiz_title": "PetSpot Bonus Gift Survey",
        "quiz_questions": [
            ("Your name | الاسم", "char_box", [], "name"),
            ("WhatsApp / Phone | رقم الموبايل", "char_box", [], "phone"),
            ("Pet type | نوع الأليف (dog/cat/other)", "char_box", [], "pet_type"),
            ("Which PetSpot branch is closer to you?", "simple_choice", [
                ("Amwaj 1 — North Coast", True),
                ("Marsa Matruh", True),
                ("Both / Not sure", True),
            ]),
            ("Which service interests you most?", "simple_choice", [
                ("Veterinary consultation", True),
                ("Grooming", True),
                ("Boarding", True),
                ("Vaccination", True),
            ]),
        ],
    },
]


def post_init_hook(env):
    """Load campaign episodes: eLearning course, knowledge articles, surveys, steps."""
    campaign = env.ref("petspot_campaign_rewards.campaign_summer_2026", raise_if_not_found=False)
    if not campaign:
        _logger.warning("PetSpot campaign record not found; skipping content load.")
        return
    if campaign.step_ids:
        _logger.info("PetSpot campaign steps already exist (%s); skipping content load.", len(campaign.step_ids))
        _sync_campaign_surveys(env, campaign)
        return

    channel = env["slide.channel"].create(
        {
            "name": "PetSpot Summer Pet Care 2026",
            "description": "7-episode knowledge quest for PetSpot El Sahel Facebook campaign.",
            "channel_type": "training",
            "enroll": "public",
            "visibility": "public",
            "is_published": True,
            "website_published": True,
        }
    )
    campaign.slide_channel_id = channel.id

    Step = env["petspot.campaign.step"]
    prev_step = False
    for ep in EPISODES:
        article = env["knowledge.article"].create(
            {
                "name": ep["title"],
                "body": ep["article_html"],
                "internal_permission": "write",
            }
        )
        slide = False
        if ep.get("slide_html"):
            slide = env["slide.slide"].create(
                {
                    "name": ep["title"],
                    "channel_id": channel.id,
                    "slide_category": "article",
                    "html_content": ep["slide_html"],
                    "is_published": True,
                    "is_preview": True,
                }
            )
        survey = _create_quiz_survey(env, campaign, ep)
        step = Step.create(
            {
                "campaign_id": campaign.id,
                "sequence": ep["sequence"],
                "title": ep["title"],
                "title_ar": ep.get("title_ar"),
                "content_type": ep["content_type"],
                "knowledge_article_id": article.id,
                "slide_id": slide.id if slide else False,
                "survey_id": survey.id,
                "issue_reward": ep["issue_reward"],
                "reward_discount_percent": ep["reward_discount_percent"],
                "facebook_message_template": ep["fb_teaser"],
                "unlock_after_step_id": prev_step.id if prev_step else False,
            }
        )
        survey.petspot_campaign_step_id = step.id
        prev_step = step

    _logger.info("PetSpot campaign content loaded: %s steps on channel %s.", len(campaign.step_ids), channel.id)

    _sync_campaign_surveys(env, campaign)


EPISODES_BY_SEQUENCE = {ep["sequence"]: ep for ep in EPISODES}


def _sync_campaign_surveys(env, campaign):
    """Populate missing quiz questions and apply mobile-friendly survey layout."""
    for step in campaign.step_ids.sorted("sequence"):
        survey = step.survey_id
        ep = EPISODES_BY_SEQUENCE.get(step.sequence)
        if not survey or not ep:
            continue
        real_questions = survey.question_and_page_ids.filtered(lambda q: not q.is_page)
        if not real_questions:
            _populate_survey_questions(env, survey, ep)
        _apply_friendly_survey_layout(env, survey, ep)
    _logger.info("Synced survey questions/sections for campaign %s.", campaign.code)


def _strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _intro_snippet(ep, max_len=120):
    text = _strip_html(ep.get("article_html", ""))
    if len(text) > max_len:
        return text[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return text


def _survey_welcome_html(ep):
    reward = ep.get("reward_discount_percent") or 0
    reward_line = ""
    if reward:
        reward_line = (
            f"<p><strong>🎁 Pass with 80%+ to receive a {reward}% discount code.</strong></p>"
            f"<p dir=\"rtl\"><strong>🎁 اجتز بـ 80%+ للحصول على كود خصم {reward}%.</strong></p>"
        )
    return f"""
<div class="petspot-quiz-welcome">
  <p><strong>Welcome to Episode {ep['sequence'] // 10}!</strong></p>
  <p dir="rtl"><strong>مرحباً بك في الحلقة {ep['sequence'] // 10}!</strong></p>
  <ul>
    <li>Tap one answer per question — big buttons, easy on mobile.</li>
    <li>Use <strong>Next</strong> to continue · you can go back if needed.</li>
    <li>No login required.</li>
  </ul>
  {reward_line}
</div>
"""


def _survey_done_html(ep):
    reward = ep.get("reward_discount_percent") or 0
    if reward:
        return (
            "<p><strong>Thank you!</strong> If you passed, your discount code appears next.</p>"
            "<p dir=\"rtl\"><strong>شكراً!</strong> إذا نجحت، سيظهر كود الخصم في الصفحة التالية.</p>"
        )
    return (
        "<p><strong>Well done!</strong> Thanks for learning with PetSpot El Sahel.</p>"
        "<p dir=\"rtl\"><strong>أحسنت!</strong> شكراً لمشاركتك مع بيت سبوت الساحل.</p>"
    )


def _section_plan(ep):
    items = ep["quiz_questions"]
    contact = [i for i, it in enumerate(items) if len(it) > 3 and it[3] in CONTACT_ROLES]
    mcq = [i for i in range(len(items)) if i not in contact]
    sections = []

    if not contact:
        sections.append(
            {
                "title": "Before you start | قبل البدء",
                "description": (
                    f"<p>{_intro_snippet(ep, 200)}</p>"
                    "<p dir=\"rtl\">اقرأ النصيحة ثم اضغط التالي للأسئلة.</p>"
                ),
                "question_indices": [],
            }
        )

    if contact:
        sections.append(
            {
                "title": "Your details | بياناتك",
                "description": (
                    "<p>Enter your details so we can send your discount code on WhatsApp.</p>"
                    "<p dir=\"rtl\">أدخل بياناتك لإرسال كود الخصم على واتساب.</p>"
                ),
                "question_indices": contact,
            }
        )

    chunk = 3 if len(mcq) > 4 else len(mcq) or 1
    for part, start in enumerate(range(0, len(mcq), chunk), start=1):
        batch = mcq[start : start + chunk]
        total_parts = (len(mcq) + chunk - 1) // chunk
        if total_parts > 1:
            title = f"Questions {part} of {total_parts} | أسئلة {part} من {total_parts}"
        else:
            title = "Quick quiz | اختبار سريع"
        sections.append({"title": title, "description": "", "question_indices": batch})

    if not sections:
        sections.append({"title": ep["title"], "description": "", "question_indices": list(range(len(items)))})
    return sections


def _apply_friendly_survey_layout(env, survey, ep):
    """Multi-page sections, welcome text, and clearer labels for mobile users."""
    survey.write(
        {
            "description": _survey_welcome_html(ep),
            "description_done": _survey_done_html(ep),
            "progression_mode": "percent",
            "users_can_go_back": True,
            "questions_layout": "page_per_section",
        }
    )

    questions = survey.question_and_page_ids.filtered(lambda q: not q.is_page).sorted("sequence")
    if len(questions) != len(ep["quiz_questions"]):
        _ensure_survey_section(env, survey, ep["title"])
        return

    for question, item in zip(questions, ep["quiz_questions"], strict=True):
        role = item[3] if len(item) > 3 else False
        qtype, answers = item[1], item[2]
        if qtype == "char_box" and role:
            question.question_placeholder = CHAR_PLACEHOLDERS.get(role, "")
        if qtype == "simple_choice" and question.suggested_answer_ids:
            for ans, (label, is_correct) in zip(question.suggested_answer_ids.sorted("sequence"), answers, strict=False):
                ans.write({"value": label, "is_correct": bool(is_correct)})

    plan = _section_plan(ep)
    survey.question_and_page_ids.filtered("is_page").unlink()

    seq = 1
    q_list = list(questions)
    Question = env["survey.question"]
    for section in plan:
        Question.create(
            {
                "survey_id": survey.id,
                "title": section["title"],
                "description": section.get("description") or False,
                "is_page": True,
                "question_type": False,
                "sequence": seq,
            }
        )
        seq += 1
        for q_idx in section["question_indices"]:
            q_list[q_idx].sequence = seq
            seq += 1


def _ensure_survey_section(env, survey, section_title):
    """Create a section page before existing questions when missing."""
    if survey.question_and_page_ids.filtered("is_page"):
        return
    questions = survey.question_and_page_ids.filtered(lambda q: not q.is_page).sorted("sequence")
    env["survey.question"].create(
        {
            "survey_id": survey.id,
            "title": section_title,
            "is_page": True,
            "question_type": False,
            "sequence": 1,
        }
    )
    for idx, question in enumerate(questions, start=2):
        question.sequence = idx


def _create_quiz_survey(env, campaign, ep):
    scoring = ep["issue_reward"]
    survey = env["survey.survey"].create(
        {
            "title": ep["quiz_title"],
            "access_mode": "public",
            "users_login_required": False,
            "questions_layout": "page_per_section",
            "scoring_type": "no_scoring" if ep["issue_reward"] and ep["reward_discount_percent"] >= 15 else "scoring_with_answers",
            "certification": ep["issue_reward"] and ep["reward_discount_percent"] < 15,
            "is_attempts_limited": True,
            "attempts_limit": 2,
            "scoring_success_min": campaign.pass_score_min or 80.0,
        }
    )
    _populate_survey_questions(env, survey, ep, start_sequence=1)
    _apply_friendly_survey_layout(env, survey, ep)
    return survey


def _populate_survey_questions(env, survey, ep, start_sequence=1):
    """Add quiz questions from episode definition when missing."""
    seq = start_sequence
    for item in ep["quiz_questions"]:
        role = item[3] if len(item) > 3 else False
        title, qtype, answers = item[0], item[1], item[2]
        vals = {
            "survey_id": survey.id,
            "sequence": seq,
            "title": title,
            "question_type": qtype,
            "constr_mandatory": True,
            "petspot_field_role": role or False,
        }
        if qtype == "char_box" and role:
            vals["question_placeholder"] = CHAR_PLACEHOLDERS.get(role, "")
        question = env["survey.question"].create(vals)
        seq += 1
        if qtype == "simple_choice":
            for idx, (label, is_correct) in enumerate(answers, start=1):
                env["survey.question.answer"].create(
                    {
                        "question_id": question.id,
                        "sequence": idx,
                        "value": label,
                        "is_correct": bool(is_correct),
                        "answer_score": 10 if is_correct else 0,
                    }
                )
