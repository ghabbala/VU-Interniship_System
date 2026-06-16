# tracking/utils/recommendation_letter.py
from io import BytesIO

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


def _safe_image_path(static_path: str):
    try:
        p = finders.find(static_path)
        return p if p else None
    except Exception:
        return None


def _safe_media_image_path(field_file):
    try:
        if field_file and getattr(field_file, "path", None):
            return field_file.path
    except Exception:
        return None
    return None


def _get_letter_settings():
    try:
        from placements.models import RecommendationLetterSettings

        return RecommendationLetterSettings.current()
    except Exception:
        return None


def _clean_faculty_name(name: str) -> str:
    if not name:
        return ""
    n = (name or "").strip()

    lowered = n.lower()
    if lowered.startswith("faculty of "):
        n = n[len("faculty of "):].strip()
        lowered = n.lower()

    if lowered.startswith("facult of "):
        n = n[len("facult of "):].strip()
        lowered = n.lower()

    if lowered.startswith("faculty-of "):
        n = n[len("faculty-of "):].strip()
        lowered = n.lower()

    if lowered.startswith("faculty"):
        parts = n.split(" ", 1)
        if len(parts) == 2 and parts[1].strip().lower().startswith("of "):
            n = parts[1].strip()[3:].strip()

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
            dx,
            dy,
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

    letter_settings = _get_letter_settings()
    logo_path = _safe_image_path("base/img/letter_logo.png")
    signature_path = (
        _safe_media_image_path(getattr(letter_settings, "signature_image", None))
        or _safe_image_path("base/img/coordinator_signature.png")
    )
    stamp_path = (
        _safe_media_image_path(getattr(letter_settings, "stamp_image", None))
        or _safe_image_path("base/img/coordinator_stamp.png")
    )

    today_str = timezone.localdate().strftime("%d %b %Y")
    student_name = _get_student_name(req)
    reg_no = _get_reg_no(req)
    faculty_name = _get_faculty_name_from_request(req)
    program_name = _get_program_name(req)
    company_name = _get_company_name(req)

    coordinator_display_name = (getattr(letter_settings, "signatory_name", "") or "").strip() or "Internship Coordinator"
    coordinator_email = ""
    coordinator_contact = ""

    if coordinator_user and not (getattr(letter_settings, "signatory_name", "") or "").strip():
        try:
            coordinator_display_name = (coordinator_user.get_full_name() or "").strip() or coordinator_user.email
        except Exception:
            coordinator_display_name = getattr(coordinator_user, "email", "") or "Internship Coordinator"

    if letter_settings:
        coordinator_email = (letter_settings.signatory_email or "").strip()
        coordinator_contact = (letter_settings.signatory_phone or "").strip()

    if coordinator_user:
        coordinator_email = coordinator_email or (getattr(coordinator_user, "email", "") or "").strip()
        coordinator_contact = coordinator_contact or _get_coordinator_contact(coordinator_user)

    c.saveState()
    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#b30000"))
    c.rect(0, height - 16, width, 16, fill=1, stroke=0)
    c.restoreState()

    left = 60
    right = width - 60
    top = height - 55

    _draw_logo_nice(c, logo_path, x_left=left, y_top=top, max_w=180, max_h=55)

    c.saveState()
    c.setStrokeColor(colors.HexColor("#d8dee8"))
    c.setLineWidth(1)
    c.line(left, top - 68, right, top - 68)
    c.restoreState()

    fac_title = f"FACULTY OF {faculty_name}".upper() if faculty_name else "FACULTY OF ______________________"
    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, top - 95, fac_title)

    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, top - 117, "OFFICE OF THE DEAN")
    c.setFillColor(colors.black)

    c.setFont("Helvetica", 11)
    c.drawString(left, top - 152, "Date:")
    c.drawString(left + 40, top - 152, today_str)

    c.drawString(left, top - 188, "Dear Sir/Madam,")

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#b30000"))
    c.drawString(left, top - 226, "RE: STUDENT INTERNSHIP/INDUSTRIAL TRAINING PLACEMENT")
    c.setFillColor(colors.black)

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "VUBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=17,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#111827"),
    )

    degree_line = program_name or "Bachelor/Diploma programme"
    org_line = company_name or "your Company/Organization"

    body_html = f"""
    Victoria University is pleased to introduce <b>{student_name}</b> (Registration No: <b>{reg_no or "N/A"}</b>),
    a student pursuing <b>{degree_line}</b>, who is seeking internship/industrial training placement with
    <b>{org_line}</b>.<br/><br/>

    The internship forms an important part of the student's academic training and is intended to strengthen
    practical skills, professional conduct, and exposure to real workplace expectations. We kindly request
    your organisation to consider the student for placement and to provide appropriate supervision during
    the training period.<br/><br/>

    Victoria University will highly appreciate any assistance rendered. For further information, please
    contact the Faculty using the details below.
    """

    p = Paragraph(body_html, body_style)
    available_width = right - left
    body_top_y = top - 255
    _, h = p.wrap(available_width, 520)
    p.drawOn(c, left, body_top_y - h)

    after_body_y = body_top_y - h - 28

    c.setFont("Times-Roman", 12)
    c.drawString(left, after_body_y, "Yours Sincerely,")

    sig_block_top = after_body_y - 70
    sig_w, sig_h = 170, 55
    stamp_w, stamp_h = 120, 120

    if signature_path:
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

    if stamp_path:
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

    name_y = sig_block_top - 20
    c.setFont("Times-Bold", 12)
    c.drawString(left, name_y, coordinator_display_name)

    configured_title = (getattr(letter_settings, "signatory_title", "") or "").strip()
    if configured_title and faculty_name and "faculty" not in configured_title.lower():
        faculty_line = f"{configured_title}, Faculty of {faculty_name}"
    elif configured_title:
        faculty_line = configured_title
    else:
        faculty_line = f"Dean, Faculty of {faculty_name}" if faculty_name else "Dean, Faculty of ______________________"

    c.setFont("Times-Roman", 12)
    c.drawString(left, name_y - 22, faculty_line)

    c.setFont("Times-Roman", 11)
    email_line = coordinator_email or "N/A"
    contact_line = coordinator_contact or "N/A"
    c.drawString(left, name_y - 70, f"Email: {email_line}   (Tel. {contact_line})")

    footer_y = 52
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#b30000"))
    c.drawCentredString(width / 2, footer_y + 32, "www.vu.ac.ug")

    footer_address = (
        (getattr(letter_settings, "footer_address", "") or "").strip()
        or "Victoria Tower, Plot No. 1-13 Jinja Road P.O. Box 30866 Kampala, Uganda"
    )
    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(width / 2, footer_y + 16, footer_address)
    c.drawCentredString(
        width / 2,
        footer_y + 4,
        "+256 759 996 146  |  marketing@vu.ac.ug  |  admissions@vu.ac.ug",
    )
    c.drawCentredString(
        width / 2,
        footer_y - 8,
        "Facebook: victoria university kampala uganda  |  Twitter/X: @vukampala  |  Instagram: victoriauniversity_kampala",
    )
    c.setFillColor(colors.black)

    c.showPage()
    c.save()

    pdf = buffer.getvalue()
    buffer.close()

    filename = f"recommendation_{reg_no or 'student'}_{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return filename, ContentFile(pdf)
