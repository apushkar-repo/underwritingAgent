#!/usr/bin/env python3
"""Generate uncurated, real-world-style mortgage PDFs for agent experiments.

Unlike ``generate_synthetic_pdfs.py``, these documents are not rendered from the
gold JSONL fixtures and do not use one predictable label/value layout. They are
still entirely fictional and contain a synthetic-data footer on every page.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "realistic_pdfs"
PAGE_WIDTH, PAGE_HEIGHT = 612, 792


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@dataclass
class Page:
    commands: list[str] = field(default_factory=list)

    def text(self, x: int, y: int, value: str, size: int = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.commands.append(
            f"BT /{font} {size} Tf 1 0 0 1 {x} {y} Tm ({_escape(value)}) Tj ET"
        )

    def line(self, x1: int, y1: int, x2: int, y2: int, width: float = 0.7) -> None:
        self.commands.append(f"{width} w {x1} {y1} m {x2} {y2} l S")

    def box(self, x: int, y: int, width: int, height: int, shade: float | None = None) -> None:
        if shade is not None:
            self.commands.append(f"{shade} g {x} {y} {width} {height} re f 0 g")
        self.commands.append(f"0.7 w {x} {y} {width} {height} re S")


class PdfDocument:
    """Tiny dependency-free PDF renderer with searchable Helvetica text."""

    def __init__(self) -> None:
        self.pages: list[Page] = []

    def add_page(self) -> Page:
        page = Page()
        self.pages.append(page)
        return page

    def save(self, path: Path) -> None:
        objects: list[bytes] = []
        # 1 catalog, 2 page tree, 3 regular font, 4 bold font
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{5 + index * 2} 0 R" for index in range(len(self.pages)))
        objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>".encode())
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        for index, page in enumerate(self.pages):
            page_id = 5 + index * 2
            stream_id = page_id + 1
            objects.append(
                (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                 f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {stream_id} 0 R >>").encode()
            )
            stream = "\n".join(page.commands).encode("latin-1", "replace")
            objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

        content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(content))
            content.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref = len(content)
        content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        content.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            content.extend(f"{offset:010d} 00000 n \n".encode())
        content.extend(
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def footer(page: Page, page_number: int) -> None:
    page.line(42, 34, 570, 34, 0.4)
    page.text(42, 20, "FICTIONAL SAMPLE - FOR SOFTWARE TESTING ONLY", 7, True)
    page.text(535, 20, f"Page {page_number}", 7)


def add_wrapped(page: Page, x: int, y: int, value: str, width: int = 82,
                size: int = 9, leading: int = 13, bold: bool = False) -> int:
    for line in textwrap.wrap(value, width=width, break_long_words=False) or [""]:
        page.text(x, y, line, size, bold)
        y -= leading
    return y


def heading(page: Page, company: str, title: str, reference: str) -> int:
    page.box(36, 704, 540, 55, 0.92)
    page.text(50, 738, company, 15, True)
    page.text(50, 716, title, 11)
    page.text(430, 716, reference, 8)
    return 682


PACKAGES = [
    {
        "folder": "intake_2026_0417_moreno",
        "loan": "UW-26-0417-A",
        "borrower": "Elena Moreno",
        "address": "1847 Larkspur Ridge, Columbus, OH 43215",
        "employer": "Northstar Pediatric Care LLC",
        "title": "Practice Operations Manager",
        "monthly": "$8,250.00",
        "annual": "$99,000",
        "loan_amount": "$356,250",
        "price": "$375,000",
        "value": "$382,000",
        "fico": "742",
        "bank_balance": "$61,884.29",
        "deposit": "$8,910.00 payroll",
        "filenames": ["1003_signed_4-17.pdf", "2025_W2_Northstar.pdf", "FCU_stmt_March.pdf", "credit_merge_0416.pdf", "contract_final_signed.pdf", "appraisal_1847_Larkspur.pdf"],
    },
    {
        "folder": "broker_upload_hayes_0821",
        "loan": "BRK-90831",
        "borrower": "Marcus Hayes",
        "address": "92 Willow Bend Court, Carmel, IN 46032",
        "employer": "Hayes Residential Design",
        "title": "Sole proprietor / architectural designer",
        "monthly": "$10,416 stated; income varies",
        "annual": "$125,000 stated",
        "loan_amount": "$483,000",
        "price": "$525,000",
        "value": "$510,000",
        "fico": "688",
        "bank_balance": "$104,229.17",
        "deposit": "$32,500.00 incoming wire - client project",
        "filenames": ["application_scan.pdf", "2025_1040_with_Schedule_C.pdf", "business_bank_apr-jun.pdf", "trimerge_90831.pdf", "purchase_agreement_v3.pdf", "valuation_report.pdf"],
    },
    {
        "folder": "wholesale_nguyen_case77",
        "loan": "WHL-77-2206",
        "borrower": "Priya Nguyen and Daniel Nguyen",
        "address": "611 South Meridian Avenue, Indianapolis, IN 46225",
        "employer": "Midwest Data Cooperative / Eastgate Community College",
        "title": "Senior data analyst / adjunct instructor",
        "monthly": "$9,475 combined",
        "annual": "$113,700 combined",
        "loan_amount": "$294,500",
        "price": "$310,000",
        "value": "$305,000",
        "fico": "719 / 701",
        "bank_balance": "$38,407.66",
        "deposit": "$14,000.00 transfer from family savings",
        "filenames": ["URLA_case77.pdf", "W2_bundle_2025.pdf", "checking_ending7721.pdf", "credit_merged.pdf", "PA_611_Meridian.pdf", "appraisal_rev1.pdf"],
    },
]


def application(pkg: dict[str, str], path: Path) -> None:
    pdf = PdfDocument(); p = pdf.add_page(); y = heading(p, "Harborline Home Finance", "Uniform Residential Loan Application", f"File {pkg['loan']}")
    p.text(42, y, "Borrower information", 11, True); y -= 22
    for label, value in [("Applicant(s)", pkg["borrower"]), ("Subject property", pkg["address"]),
                         ("Employment / business", pkg["employer"]), ("Position", pkg["title"]),
                         ("Gross monthly income (stated)", pkg["monthly"])]:
        p.text(48, y, label, 8, True); p.text(230, y, value, 9); y -= 24
    p.line(42, y + 8, 570, y + 8); y -= 12
    p.text(42, y, "Loan and property information", 11, True); y -= 24
    p.text(48, y, f"Purchase price: {pkg['price']}", 9); p.text(310, y, f"Loan amount requested: {pkg['loan_amount']}", 9); y -= 25
    p.text(48, y, "Occupancy: Primary residence", 9); p.text(310, y, "Purpose: Purchase", 9); y -= 34
    p.box(42, y - 90, 528, 105); p.text(52, y - 5, "Declarations and acknowledgments", 10, True)
    y = add_wrapped(p, 52, y - 25, "The applicant certifies that the information supplied is true and complete. The lender may verify employment, assets, credit, and property information.", 88, 8, 12)
    p.text(52, y - 20, "Borrower signature: /s/ Electronic consent on file", 8)
    p.text(360, y - 20, "Application date: 04/17/2026", 8); footer(p, 1); pdf.save(path)


def _form_box(page: Page, x: int, y: int, width: int, height: int,
              label: str, value: str = "", value_size: int = 9) -> None:
    page.box(x, y, width, height)
    page.text(x + 4, y + height - 10, label, 6, True)
    if value:
        page.text(x + 7, y + 8, value, value_size)


def w2_document(pkg: dict[str, str], path: Path, index: int) -> None:
    """Render a recognizably boxed Copy B W-2 without copying an official form."""
    pdf = PdfDocument(); p = pdf.add_page()
    p.text(36, 754, "2025", 20, True); p.text(95, 754, "Wage and Tax Statement", 14, True)
    p.text(470, 754, "Form W-2", 15, True); p.text(470, 739, "Copy B", 9, True)
    p.text(36, 730, "Department of the Treasury - Internal Revenue Service", 7)
    employer_id = "31-8472910" if index == 0 else "35-6291048"
    wages = "$99,000.00" if index == 0 else "$91,200.00"
    federal = "$12,846.00" if index == 0 else "$10,972.00"
    employee = pkg["borrower"].split(" and ")[0]
    _form_box(p, 36, 660, 270, 58, "a Employee's social security number", "XXX-XX-4821")
    _form_box(p, 306, 660, 135, 58, "1 Wages, tips, other compensation", wages)
    _form_box(p, 441, 660, 135, 58, "2 Federal income tax withheld", federal)
    _form_box(p, 36, 570, 270, 90, "b Employer identification number / c Employer name and address",
              f"{employer_id}  {pkg['employer']}", 7)
    p.text(43, 583, "4400 Meridian Park Drive, Indianapolis, IN 46204", 7)
    _form_box(p, 306, 615, 135, 45, "3 Social security wages", wages)
    _form_box(p, 441, 615, 135, 45, "4 Social security tax withheld", "$6,138.00")
    _form_box(p, 306, 570, 135, 45, "5 Medicare wages and tips", wages)
    _form_box(p, 441, 570, 135, 45, "6 Medicare tax withheld", "$1,435.50")
    _form_box(p, 36, 485, 270, 85, "e Employee's first name and initial / Last name / Address", employee, 8)
    p.text(43, 503, pkg["address"], 7)
    for x, number, label, value in [(306, "7", "Social security tips", "$0.00"),
                                     (441, "8", "Allocated tips", "$0.00")]:
        _form_box(p, x, 525, 135, 45, f"{number} {label}", value)
    _form_box(p, 306, 485, 135, 40, "10 Dependent care benefits", "$0.00")
    _form_box(p, 441, 485, 135, 40, "11 Nonqualified plans", "$0.00")
    _form_box(p, 36, 390, 135, 95, "12a Code", "D   $6,500.00")
    _form_box(p, 171, 390, 135, 95, "12b Code", "DD  $8,940.00")
    _form_box(p, 306, 390, 135, 95, "13 Statutory / retirement / sick pay", "Retirement plan: X", 7)
    _form_box(p, 441, 390, 135, 95, "14 Other", "Health premium $2,184", 7)
    _form_box(p, 36, 320, 90, 70, "15 State / Employer state ID", "IN / 00918472", 7)
    _form_box(p, 126, 320, 115, 70, "16 State wages", wages)
    _form_box(p, 241, 320, 105, 70, "17 State income tax", "$3,118.50")
    _form_box(p, 346, 320, 115, 70, "18 Local wages", wages)
    _form_box(p, 461, 320, 115, 70, "19 Local income tax / locality", "$1,287.00 / IN", 7)
    p.text(36, 293, "This information is being furnished to the Internal Revenue Service.", 7, True)
    p.text(36, 276, "Keep Copy B with your federal tax records. Control no. 25-0048291", 7)
    p.box(36, 80, 540, 160, .96); p.text(48, 220, "Employee filing reference", 9, True)
    add_wrapped(p, 48, 200, "The boxes and arrangement are representative training data. Names, identification numbers, wages, employers, and addresses are entirely fictional.", 88, 8, 12)
    footer(p, 1); pdf.save(path)


def tax_return_document(pkg: dict[str, str], path: Path) -> None:
    """Render a four-page 1040 and Schedule C-style filing package."""
    pdf = PdfDocument()
    # Page 1: filing identity and income.
    p = pdf.add_page(); p.text(36, 754, "Form", 8); p.text(36, 727, "1040", 26, True)
    p.text(115, 748, "U.S. Individual Income Tax Return", 15, True); p.text(500, 748, "2025", 18, True)
    p.line(36, 718, 576, 718, 1.2); p.text(36, 700, "Filing status", 8, True); p.text(120, 700, "Single  [X]   Married filing jointly [ ]   Head of household [ ]", 8)
    _form_box(p, 36, 645, 270, 45, "Your first name and initial / Last name", pkg["borrower"])
    _form_box(p, 306, 645, 270, 45, "Your social security number", "XXX-XX-7318")
    _form_box(p, 36, 585, 540, 60, "Home address", "92 Willow Bend Court, Carmel, IN 46032", 8)
    p.text(36, 560, "Digital assets: At any time during 2025, did you receive or dispose of a digital asset?  Yes [ ]  No [X]", 7)
    p.text(36, 532, "Income", 12, True)
    income_rows = [("1a", "Total amount from Form(s) W-2", "0"), ("3b", "Ordinary dividends", "1,184"),
                   ("7", "Capital gain or (loss)", "1,481"), ("8", "Additional income from Schedule 1, line 10", "112,240"),
                   ("9", "Total income", "114,905"), ("10", "Adjustments to income from Schedule 1", "7,900"),
                   ("11", "Adjusted gross income", "107,005")]
    y = 508
    for num, label, value in income_rows:
        p.text(42, y, num, 7, True); p.text(72, y, label, 8); p.text(490, y, value, 8); p.line(36, y - 5, 576, y - 5, .25); y -= 25
    p.text(36, y - 5, "Standard deduction", 10, True); p.text(490, y - 5, "15,675", 8); y -= 35
    p.text(36, y, "Taxable income", 10, True); p.text(490, y, "91,330", 9, True); footer(p, 1)

    # Page 2: tax, payments, refund/amount owed and signature.
    p = pdf.add_page(); p.text(36, 754, "Form 1040 (2025)", 9, True); p.text(465, 754, "Page 2", 8); p.line(36, 744, 576, 744)
    sections = [("Tax and credits", [("16", "Tax", "15,204"), ("19", "Child tax credit", "0"), ("24", "Total tax", "22,416")]),
                ("Payments", [("25a", "Federal income tax withheld", "0"), ("26", "2025 estimated tax payments", "24,000"), ("33", "Total payments", "24,000")]),
                ("Refund", [("34", "Overpayment", "1,584"), ("35a", "Amount refunded to checking ending 2291", "1,584")])]
    y = 710
    for title, rows in sections:
        p.text(36, y, title, 12, True); y -= 24
        for num, label, value in rows:
            p.text(42, y, num, 7, True); p.text(76, y, label, 8); p.text(490, y, value, 8); p.line(36, y - 5, 576, y - 5, .25); y -= 25
        y -= 16
    p.box(36, 180, 540, 115); p.text(45, 276, "Sign here", 10, True)
    add_wrapped(p, 45, 255, "Under penalties of perjury, I declare that I have examined this return and accompanying schedules and statements.", 88, 8, 12)
    p.line(50, 210, 280, 210); p.text(50, 196, "Your signature: electronically filed", 7)
    p.line(350, 210, 545, 210); p.text(350, 196, "Date: 03/09/2026", 7); footer(p, 2)

    # Page 3: Schedule 1.
    p = pdf.add_page(); p.text(36, 754, "SCHEDULE 1 (Form 1040)", 15, True)
    p.text(36, 734, "Additional Income and Adjustments to Income", 11); p.text(480, 734, "2025", 14, True); p.line(36, 720, 576, 720)
    p.text(36, 690, "Part I - Additional Income", 11, True)
    rows = [("3", "Business income or (loss). Attach Schedule C", "112,240"), ("5", "Rental real estate, royalties, partnerships", "0"),
            ("8z", "Other income", "0"), ("10", "Additional income. Add lines 1 through 9", "112,240")]
    y = 660
    for num, label, value in rows:
        p.text(42, y, num, 7, True); p.text(75, y, label, 8); p.text(490, y, value, 8); p.line(36, y - 5, 576, y - 5, .25); y -= 28
    y -= 18; p.text(36, y, "Part II - Adjustments to Income", 11, True); y -= 30
    for num, label, value in [("15", "Deductible part of self-employment tax", "7,900"), ("26", "Total adjustments to income", "7,900")]:
        p.text(42, y, num, 7, True); p.text(75, y, label, 8); p.text(490, y, value, 8); y -= 28
    footer(p, 3)

    # Page 4: Schedule C details and missing-current-P&L signal.
    p = pdf.add_page(); p.text(36, 754, "SCHEDULE C (Form 1040)", 15, True)
    p.text(36, 734, "Profit or Loss From Business", 11); p.text(480, 734, "2025", 14, True); p.line(36, 720, 576, 720)
    _form_box(p, 36, 660, 540, 48, "A Principal business or profession", "Architectural and residential design services")
    _form_box(p, 36, 612, 270, 48, "B Business code", "541310")
    _form_box(p, 306, 612, 270, 48, "D Employer ID number", "XX-XXX1048")
    p.text(36, 580, "Part I - Income", 11, True); y = 554
    rows = [("1", "Gross receipts or sales", "178,420"), ("2", "Returns and allowances", "0"),
            ("7", "Gross income", "178,420"), ("8", "Advertising", "4,820"),
            ("10", "Commissions and fees", "7,115"), ("18", "Office expense", "9,760"),
            ("20b", "Rent or lease - other business property", "18,000"), ("22", "Supplies", "6,485"),
            ("27a", "Other expenses", "20,000"), ("28", "Total expenses", "66,180"),
            ("31", "Net profit", "112,240")]
    for num, label, value in rows:
        p.text(42, y, num, 7, True); p.text(75, y, label, 8); p.text(490, y, value, 8, num == "31"); p.line(36, y - 5, 576, y - 5, .2); y -= 22
    p.box(36, 85, 540, 72, .94); p.text(45, 137, "LENDER FILE NOTE - NOT PART OF TAX FILING", 8, True)
    add_wrapped(p, 45, 120, "Broker upload contained the filed 2025 return. No 2026 year-to-date profit and loss statement or current business balance sheet was included.", 88, 8, 11)
    footer(p, 4); pdf.save(path)


def income(pkg: dict[str, str], path: Path, index: int) -> None:
    if index == 1:
        tax_return_document(pkg, path)
    else:
        w2_document(pkg, path, index)


def bank(pkg: dict[str, str], path: Path, index: int) -> None:
    pdf = PdfDocument(); p = pdf.add_page(); y = heading(p, "Community First Credit Union", "ACCOUNT STATEMENT", "Cycle ending 04/30/2026")
    p.text(42, y, pkg["borrower"], 10, True); p.text(365, y, "Account: CHECKING ****7721", 8); y -= 18
    p.text(42, y, pkg["address"], 8); y -= 35
    p.box(42, y - 70, 528, 84, .95); p.text(52, y - 6, "Opening balance", 8); p.text(180, y - 6, "$31,102.44", 9, True)
    p.text(310, y - 6, "Deposits / credits", 8); p.text(455, y - 6, "$22,814.62", 9, True)
    p.text(52, y - 36, "Withdrawals", 8); p.text(180, y - 36, "$15,509.40", 9, True)
    p.text(310, y - 36, "Closing balance", 8); p.text(455, y - 36, pkg["bank_balance"], 9, True); y -= 100
    p.text(42, y, "Transaction activity", 10, True); y -= 24
    transactions = [("04/03", "ACH CREDIT - PAYROLL", "$2,885.23"), ("04/08", "MORTGAGE / RENT PAYMENT", "-$2,140.00"),
                    ("04/15", pkg["deposit"], "$14,000.00" if index == 2 else ("$32,500.00" if index == 1 else "$8,910.00")),
                    ("04/22", "CARD PAYMENT", "-$1,284.16"), ("04/30", "INTEREST CREDIT", "$4.39")]
    for date, desc, amount in transactions:
        p.text(48, y, date, 8); p.text(105, y, desc, 8); p.text(475, y, amount, 8); p.line(45, y - 6, 555, y - 6, .25); y -= 24
    y -= 14; y = add_wrapped(p, 46, y, "Account holder reminder: retain records supporting unusual or non-payroll deposits. Availability of funds does not establish an acceptable source for lending purposes.", 90, 8, 12)
    footer(p, 1); pdf.save(path)


def credit(pkg: dict[str, str], path: Path) -> None:
    pdf = PdfDocument(); p = pdf.add_page(); y = heading(p, "Tri-Bureau Credit Services", "MERGED CREDIT REPORT", f"Reference {pkg['loan']}")
    p.text(42, y, f"Consumer: {pkg['borrower']}", 10, True); p.text(410, y, f"Scores: {pkg['fico']}", 10, True); y -= 32
    p.text(42, y, "Public records: NONE REPORTED     Fraud alert: NONE     Inquiries (90 days): 2", 8); y -= 35
    p.text(42, y, "TRADELINE", 8, True); p.text(260, y, "BALANCE", 8, True); p.text(350, y, "PAYMENT", 8, True); p.text(445, y, "STATUS", 8, True); y -= 18
    rows = [("Metro Auto Finance ****8812", "$18,740", "$486", "Pays as agreed"),
            ("Union Bank Visa ****1094", "$3,284", "$96", "Pays as agreed"),
            ("Home Goods Retail ****4031", "$612", "$35", "Pays as agreed"),
            ("Student Loan Servicing ****2290", "$21,908", "$188", "Pays as agreed")]
    for name, balance, payment, status in rows:
        p.text(42, y, name, 8); p.text(260, y, balance, 8); p.text(350, y, payment, 8); p.text(445, y, status, 8); p.line(40, y - 6, 560, y - 6, .25); y -= 24
    y -= 20; p.box(42, y - 42, 528, 57, .95); p.text(52, y - 5, "TOTAL MONTHLY OBLIGATIONS SHOWN", 9, True); p.text(450, y - 5, "$805", 10, True)
    p.text(52, y - 27, "Housing payment is not included in the total above.", 8); footer(p, 1); pdf.save(path)


CONTRACT_SECTIONS = [
    ("1. PROPERTY AND PARTIES", "Buyer agrees to purchase and Seller agrees to convey the land, improvements, fixtures, rights, and appurtenances commonly known as the Property. Included fixtures consist of attached lighting, plumbing fixtures, built-in appliances, landscaping, window treatments, garage controls, and permanently installed equipment unless specifically excluded."),
    ("2. PURCHASE PRICE AND EARNEST MONEY", "The purchase price shall be paid through earnest money, proceeds of Buyer's financing, and funds due from Buyer at settlement. Earnest money will be held in the listing broker's escrow account and credited at closing. Failure to deposit earnest money when due may constitute a default after notice and an opportunity to cure."),
    ("3. FINANCING CONTINGENCY", "This Agreement is contingent upon Buyer obtaining conventional financing on commercially reasonable terms. Buyer will make timely application, provide truthful financial information, respond to lender requests, and avoid changes in credit or employment that could impair qualification. Loan approval excludes conditions customarily satisfied at closing."),
    ("4. APPRAISAL", "Buyer's obligation is contingent upon the Property appraising at not less than the purchase price. If the opinion of value is lower, Buyer may terminate, waive the contingency, or propose a price adjustment. Seller may accept, reject, or counter any proposed adjustment. Notices under this section must be delivered within the stated contingency period."),
    ("5. INSPECTIONS AND DUE DILIGENCE", "Buyer may obtain general home, structural, roof, sewer, environmental, radon, pest, and other inspections by qualified professionals. Buyer accepts responsibility for inspection costs and damage caused by testing. Written requests for repair or credit must identify the supporting report and be delivered before expiration of the inspection period."),
    ("6. TITLE AND SURVEY", "Seller shall convey marketable title by general warranty deed, subject only to permitted exceptions. Buyer may obtain an owner's title insurance policy and survey. Seller shall have a reasonable cure period for title defects. Real estate taxes, assessments, rents, association charges, and utilities will be prorated as of closing."),
    ("7. DISCLOSURES", "Seller shall provide disclosures required by applicable law, including known material defects and lead-based paint information when applicable. Buyer acknowledges that brokers do not independently verify property condition, boundaries, school assignments, square footage, environmental conditions, or future land use."),
    ("8. RISK OF LOSS AND POSSESSION", "Risk of material casualty remains with Seller until closing. If material damage or condemnation occurs before closing, Buyer may terminate or proceed with available insurance proceeds and lawful credits. Possession will be delivered at closing unless a separate written occupancy agreement provides otherwise."),
    ("9. SETTLEMENT", "Closing will occur through the selected title company on or before the target date, subject to written extension. Buyer and Seller authorize electronic delivery of settlement statements and documents. Funds required at closing must be delivered in a form acceptable to the settlement agent and consistent with wire-fraud safeguards."),
    ("10. DEFAULT AND REMEDIES", "If Buyer defaults without contractual excuse, earnest money may be released as liquidated damages where permitted. If Seller defaults, Buyer may seek return of earnest money and other remedies available by law. A party seeking enforcement may recover costs only when authorized by statute, rule, or written agreement."),
    ("11. NOTICES", "Notices must be in writing and may be delivered personally, by recognized overnight carrier, or electronically to the addresses designated by the parties. Notice is effective when received, except that an electronic notice transmitted after 8:00 p.m. local time is deemed received the following business day."),
    ("12. BROKERAGE", "Buyer and Seller acknowledge the brokerage relationships previously disclosed. Brokers are not parties to this Agreement and do not provide legal, tax, engineering, environmental, or lending advice. Each party has been encouraged to consult appropriate independent professionals."),
    ("13. ASSIGNMENT; GOVERNING LAW", "Buyer may not assign this Agreement without Seller's written consent except to an entity controlled by Buyer when Buyer remains liable. The Agreement is governed by the law of the state where the Property is located. Invalid provisions will be severed without impairing the remaining terms."),
    ("14. ENTIRE AGREEMENT", "This Agreement, incorporated addenda, and written amendments contain the complete agreement of the parties. Oral representations are not binding. Amendments and waivers must be signed. Counterparts and verified electronic signatures are effective as originals."),
]


def contract(pkg: dict[str, str], path: Path) -> None:
    """Create a six-page agreement with dense boilerplate and signed addenda."""
    pdf = PdfDocument()
    p = pdf.add_page(); y = heading(p, "STATEWIDE REALTORS ASSOCIATION", "Residential Real Estate Purchase Agreement", "Form RPA-12 / Rev. 01-26")
    p.text(42, y, "A. KEY TERMS", 11, True); y -= 25
    terms = [("Buyer", pkg["borrower"]), ("Seller", "Juniper Property Holdings LLC"),
             ("Property", pkg["address"]), ("Purchase price", pkg["price"]),
             ("Earnest money", "$5,000 due within 3 business days"),
             ("Financing", f"Conventional loan; anticipated amount {pkg['loan_amount']}"),
             ("Closing", "On or before June 12, 2026"), ("Possession", "At recording and disbursement"),
             ("Seller contribution", "Up to $4,500 toward allowable Buyer closing costs")]
    for label, value in terms:
        p.box(42, y - 23, 145, 26, .96); p.box(187, y - 23, 383, 26)
        p.text(48, y - 13, label, 7, True); p.text(194, y - 13, value, 8); y -= 26
    y -= 18; p.text(42, y, "CONTINGENCY DEADLINES", 10, True); y -= 23
    for item in ("Loan application: 5 days", "Inspection response: 10 days", "Appraisal response: 5 days after receipt", "Title objection: 5 days after commitment"):
        p.text(50, y, f"[X] {item}", 8); y -= 20
    footer(p, 1)

    # Four dense terms pages, with varied sections and initials.
    chunks = [CONTRACT_SECTIONS[0:4], CONTRACT_SECTIONS[4:8], CONTRACT_SECTIONS[8:11], CONTRACT_SECTIONS[11:14]]
    for page_number, sections in enumerate(chunks, start=2):
        p = pdf.add_page(); p.text(36, 754, "RESIDENTIAL REAL ESTATE PURCHASE AGREEMENT", 9, True)
        p.text(470, 754, f"Page {page_number} of 6", 8); p.line(36, 742, 576, 742)
        y = 716
        for title, body in sections:
            p.text(40, y, title, 9, True); y -= 18
            y = add_wrapped(p, 46, y, body, 96, 8, 11)
            y -= 12
            if y > 135:
                p.text(46, y, "Buyer initials: ________     Seller initials: ________", 7); y -= 25
        p.box(36, 62, 540, 34, .96); p.text(44, 76, f"Property: {pkg['address']}    File: {pkg['loan']}", 7)
        footer(p, page_number)

    # Final addenda and signatures page.
    p = pdf.add_page(); p.text(36, 754, "ADDENDA, ACCEPTANCE, AND SIGNATURES", 12, True)
    p.text(470, 754, "Page 6 of 6", 8); p.line(36, 742, 576, 742); y = 714
    p.text(40, y, "INCORPORATED ADDENDA", 9, True); y -= 24
    for label, checked in [("Financing Contingency Addendum", True), ("Appraisal Gap Addendum", True),
                           ("Property Inspection Addendum", True), ("Lead-Based Paint Disclosure", False),
                           ("Seller Property Disclosure", True), ("Homeowners Association Addendum", False)]:
        p.text(48, y, f"[{'X' if checked else ' '}] {label}", 8); y -= 20
    y -= 12; p.text(40, y, "ADDITIONAL PROVISION", 9, True); y -= 20
    y = add_wrapped(p, 46, y, "Seller will provide a one-year home warranty not exceeding $650. Personal property has no assigned value. Any lender-required repair must be agreed in a writing signed by both parties.", 94, 8, 12)
    y -= 30; p.text(40, y, "ACCEPTANCE", 9, True); y -= 20
    y = add_wrapped(p, 46, y, "The parties acknowledge receipt of all six pages and incorporated addenda, understand that this is a legally binding contract, and have had the opportunity to obtain independent legal and tax advice.", 94, 8, 12)
    y -= 35
    signatures = [("Buyer 1: /s/ electronic signature", "04/14/2026  7:42 PM"),
                  ("Buyer 2 (if any): /s/ electronic signature", "04/14/2026  7:44 PM"),
                  ("Seller: /s/ Jordan Bell, authorized manager", "04/15/2026  9:18 AM")]
    for label, date in signatures:
        p.line(46, y, 355, y); p.line(400, y, 555, y); p.text(46, y - 14, label, 7); p.text(400, y - 14, date, 7); y -= 48
    p.box(36, 82, 540, 70, .94); p.text(45, 132, "ELECTRONIC TRANSACTION AUDIT", 8, True)
    p.text(45, 114, f"Envelope: SYN-{pkg['loan']}-A9F2     Status: Completed", 7)
    p.text(45, 98, "Certificate hashes and network addresses omitted from this fictional training sample.", 7)
    footer(p, 6); pdf.save(path)


def appraisal(pkg: dict[str, str], path: Path) -> None:
    pdf = PdfDocument(); p = pdf.add_page(); y = heading(p, "Summit Valuation Group", "Uniform Residential Appraisal Report - Summary", "Form 1004")
    p.text(42, y, f"Property: {pkg['address']}", 10, True); y -= 25
    p.text(42, y, "Property rights: Fee simple", 8); p.text(290, y, "Occupancy: Owner occupied", 8); y -= 21
    p.text(42, y, "Neighborhood: Suburban / stable", 8); p.text(290, y, "Condition: C3", 8); y -= 32
    p.text(42, y, "SALES COMPARISON APPROACH", 10, True); y -= 22
    rows = [("Subject", pkg["address"].split(",")[0], "--"), ("Comparable 1", "744 Madison Street", "$312,000"),
            ("Comparable 2", "508 Meridian Avenue", "$299,500"), ("Comparable 3", "830 Palmer Street", "$318,000")]
    for label, address, sale in rows:
        p.text(48, y, label, 8, True); p.text(145, y, address, 8); p.text(445, y, sale, 8); y -= 22
    y -= 16; p.box(42, y - 54, 528, 68, .93); p.text(52, y - 7, "OPINION OF MARKET VALUE", 9, True); p.text(445, y - 7, pkg["value"], 13, True)
    p.text(52, y - 32, "Effective date: 04/20/2026", 8); y -= 86
    y = add_wrapped(p, 42, y, "Reconciliation: Greatest weight was placed on the two most proximate closed sales. The final opinion reflects observed condition, gross living area, and market-supported adjustments.", 94, 8, 12)
    footer(p, 1); pdf.save(path)


BUILDERS = (application, income, bank, credit, contract, appraisal)
DOC_TYPES = ("loan_application", "income_evidence", "asset_statement", "credit_report", "purchase_contract", "appraisal")


def main() -> None:
    manifest = {
        "description": "Uncurated, fictional, real-world-style PDFs for model-based document intake",
        "warning": "No expected-results file is provided; filenames and layouts intentionally vary.",
        "packages": [],
    }
    for index, pkg in enumerate(PACKAGES):
        documents = []
        folder = OUTPUT_DIR / pkg["folder"]
        for doc_type, filename, builder in zip(DOC_TYPES, pkg["filenames"], BUILDERS):
            path = folder / filename
            if builder in (income, bank):
                builder(pkg, path, index)
            else:
                builder(pkg, path)
            documents.append({"document_type_hint": doc_type, "path": f"{pkg['folder']}/{filename}"})
        manifest["packages"].append({"intake_reference": pkg["loan"], "folder": pkg["folder"], "documents": documents})
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(PACKAGES) * len(BUILDERS)} realistic PDFs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
