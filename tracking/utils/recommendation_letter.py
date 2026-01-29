# tracking/utils/recommendation_letter.py
from io import BytesIO

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def _safe_image_path(static_path: str):
    try:
        p = finders.find(static_path)
        return p if p else None
    except Exception:
        return None


def _clean_faculty_name(name: str) -> str:
    """
    Prevent: 'FACULTY OF FACULTY OF ...'
    Handles inputs like:
      - 'Faculty of Science and Technology'
      - 'FACULTY OF SCIENCE AND TECHNOLOGY'
      - 'FACULTY OF Faculty of Science and Technology'
    Returns clean: 'Science and Technology' or 'SCIENCE AND TECHNOLOGY' (original casing preserved lightly)
    """
    if not name:
        return ""
    n = (name or "").strip()

    # remove repeated prefixes (case-insensitive)
    lowered = n.lower()
    if lowered.startswith("faculty of "):
        n = n[len("faculty of "):].strip()
        lowered = n.lower()

    if lowered.startswith("facult of "):  # catch typos like "Facult of"
        n = n[len("facult of "):].strip()
        lowered = n.lower()

    if lowered.startswith("faculty-of "):
        n = n[len("faculty-of "):].strip()
        lowered = n.lower()

    if lowered.startswith("faculty"):
        # Some data might store just "Faculty" then name after
        # (rare, but safe)
        parts = n.split(" ", 1)
        if len(parts) == 2 and parts[1].strip().lower().startswith("of "):
            n = parts[1].strip()[3:].strip()

    # Also remove if already "FACULTY OF ..." in uppercase form
    if n.upper().startswith("FACULTY OF "):
        n = n[10:].strip()

    return n


def _get_faculty_name_from_request(req) -> str:
    try:
        program = getattr(req.student, "program", None)
        dept = getattr(program, "department", None) if program else None
        fac = getattr(dept, "faculty", None) if dept else None
        name = getattr(fac, "name", "") if fac else ""
        return _clean_faculty_name((name or "").strip())
    except Exception:
        return ""


def _get_program_name(req) -> str:
    try:
        program = getattr(req.student, "program", None)
        name = getattr(program, "name", "") or (str(program) if program else "")
        return (name or "").strip()
    except Exception:
        return ""


def _get_student_name(req) -> str:
    u = getattr(getattr(req, "student", None), "user", None)
    if not u:
        return "________________________"
    try:
        full = (u.get_full_name() or "").strip()
    except Exception:
        full = ""
    return full or (getattr(u, "email", "") or "").strip() or "________________________"


def _get_reg_no(req) -> str:
    return (getattr(getattr(req, "student", None), "reg_no", "") or "").strip()


def _get_company_name(req) -> str:
    if getattr(req, "preferred_company", None):
        return (req.preferred_company.name or "").strip()
    return (getattr(req, "proposed_company_name", "") or "").strip()


def _get_coordinator_contact(coordinator_user) -> str:
    if not coordinator_user:
        return ""
    for attr in ["phone", "phone_number", "contact", "mobile", "tel"]:
        v = (getattr(coordinator_user, attr, "") or "").strip()
        if v:
            return v
    sp = getattr(coordinator_user, "staff_profile", None)
    if sp:
        for attr in ["phone", "phone_number", "contact", "mobile", "tel"]:
            v = (getattr(sp, attr, "") or "").strip()
            if v:
                return v
    return ""


def _draw_logo_nice(c, logo_path: str, x_left: float, y_top: float, max_w: float, max_h: float):
    """
    Draw logo starting from same left margin as paragraphs (x_left),
    scaled proportionally (no stretching).
    """
    if not logo_path:
        return
    try:
        img = ImageReader(logo_path)
        iw, ih = img.getSize()
        if not iw or not ih:
            return

        scale = min(max_w / float(iw), max_h / float(ih))
        draw_w = iw * scale
        draw_h = ih * scale

        dx = x_left
        dy = (y_top - max_h) + (max_h - draw_h) / 2.0

        c.drawImage(
            img,
            dx, dy,
            width=draw_w,
            height=draw_h,
            mask="auto",
            preserveAspectRatio=True,
            anchor="sw",
        )
    except Exception:
        return


def generate_recommendation_letter_pdf(req, coordinator_user=None):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Assets
    logo_path = _safe_image_path("base/img/letter_logo.png")
    signature_path = _safe_image_path("base/img/coordinator_signature.png")
    stamp_path = _safe_image_path("base/img/coordinator_stamp.png")

    # Data
    today_str = timezone.localdate().strftime("%d %b %Y")
    student_name = _get_student_name(req)
    reg_no = _get_reg_no(req)

    # ✅ cleaned faculty name (no "Faculty of" inside it)
    faculty_name = _get_faculty_name_from_request(req)

    program_name = _get_program_name(req)
    company_name = _get_company_name(req)

    coordinator_display_name = "Internship Coordinator"
    coordinator_email = ""
    coordinator_contact = ""

    if coordinator_user:
        try:
            coordinator_display_name = (coordinator_user.get_full_name() or "").strip() or coordinator_user.email
        except Exception:
            coordinator_display_name = getattr(coordinator_user, "email", "") or "Internship Coordinator"
        coordinator_email = (getattr(coordinator_user, "email", "") or "").strip()
        coordinator_contact = _get_coordinator_contact(coordinator_user)

    # Yellow background
    c.saveState()
    c.setFillColor(colors.Color(1, 0.98, 0.80))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.restoreState()

    # Layout
    left = 60
    right = width - 60
    top = height - 55

    # Logo (aligned)
    _draw_logo_nice(c, logo_path, x_left=left, y_top=top, max_w=180, max_h=55)

    # ✅ Heading (NO duplication)
    fac_title = f"FACULTY OF {faculty_name}".upper() if faculty_name else "FACULTY OF ______________________"
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(width / 2, top - 90, fac_title)

    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, top - 112, "OFFICE OF THE DEAN")

    # Date
    c.setFont("Helvetica", 11)
    c.drawString(left, top - 155, "Date:")
    c.drawString(left + 40, top - 155, today_str)

    # Dear Sir/Madam
    c.drawString(left, top - 190, "Dear Sir/Madam,")

    # RE
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, top - 235, "RE: STUDENT INTERNSHIP/INDUSTRIAL TRAINING PLACEMENT")

    # Body (justified)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "VUBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=16,
        alignment=TA_JUSTIFY,
        textColor=colors.black,
    )

    degree_line = program_name or "Bachelor/Diploma programme"
    org_line = company_name or "your Company/Organization"

    body_html = f"""
    It is my pleasure to introduce to you <b>{student_name}</b> (Reg No: <b>{reg_no or "—"}</b>),
    who is our student at Victoria University, pursuing <b>{degree_line}</b>,
    and he/she is interested in carrying out his/her internship/industrial training from <b>{org_line}</b>.
    Internship/industrial training today is mandatory, but it is also our University aim to promote experiential learning,
    where students graduate with extra knowledge and experience from the real work environment.<br/><br/>

    We shall highly appreciate any assistance rendered to him/her.
    For any further inquiries please do not hesitate to contact the Faculty through the email and phone number below;
    """

    p = Paragraph(body_html, body_style)
    available_width = right - left
    body_top_y = top - 265
    w, h = p.wrap(available_width, 520)
    p.drawOn(c, left, body_top_y - h)

    after_body_y = body_top_y - h - 28

    # Yours sincerely
    c.setFont("Times-Roman", 12)
    c.drawString(left, after_body_y, "Yours Sincerely,")

    # Signature + stamp (pushed down)
    sig_block_top = after_body_y - 70
    sig_w, sig_h = 170, 55
    stamp_w, stamp_h = 120, 120

    if coordinator_user and signature_path:
        try:
            c.drawImage(
                ImageReader(signature_path),
                left,
                sig_block_top,
                width=sig_w,
                height=sig_h,
                mask="auto",
                preserveAspectRatio=True,
                anchor="sw",
            )
        except Exception:
            pass

    if coordinator_user and stamp_path:
        try:
            c.drawImage(
                ImageReader(stamp_path),
                right - stamp_w,
                sig_block_top - 38,
                width=stamp_w,
                height=stamp_h,
                mask="auto",
                preserveAspectRatio=True,
                anchor="sw",
            )
        except Exception:
            pass

    # Coordinator details
    name_y = sig_block_top - 20
    c.setFont("Times-Bold", 12)
    c.drawString(left, name_y, coordinator_display_name)

    # ✅ faculty line (no duplication)
    # If you want "Dean, Faculty of X" specifically:
    faculty_line = f"Dean, Faculty of {faculty_name}" if faculty_name else "Dean, Faculty of ______________________"

    c.setFont("Times-Roman", 12)
    c.drawString(left, name_y - 22, faculty_line)

    # Email + contact
    c.setFont("Times-Roman", 11)
    email_line = coordinator_email or "—"
    contact_line = coordinator_contact or "—"
    c.drawString(left, name_y - 70, f"Email: {email_line}   (Tel. {contact_line})")

    # Footer (no overlap)
    footer_y = 52
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.red)
    c.drawCentredString(width / 2, footer_y + 32, "www.vu.ac.ug")

    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(
        width / 2,
        footer_y + 16,
        "Victoria Tower, Plot No. 1-13 Jinja Road P.O. Box 30866 Kampala, Uganda"
    )
    c.drawCentredString(
        width / 2,
        footer_y + 4,
        "+256 759 996 146  |  marketing@vu.ac.ug  |  admissions@vu.ac.ug"
    )
    c.drawCentredString(
        width / 2,
        footer_y - 8,
        "Facebook: victoria university kampala uganda  |  Twitter/X: @vukampala  |  Instagram: victoriauniversity_kampala"
    )
    c.setFillColor(colors.black)

    c.showPage()
    c.save()

    pdf = buffer.getvalue()
    buffer.close()

    filename = f"recommendation_{reg_no or 'student'}_{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return filename, ContentFile(pdf)
