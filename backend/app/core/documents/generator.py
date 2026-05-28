import logging
import os
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class InvoiceItemSchema(BaseModel):
    name: str = Field(..., description="Description of the goods")
    hs_code: str = Field(..., description="10-digit HS code (ТН ВЭД)")
    qty: float = Field(..., description="Quantity of the goods")
    unit: str = Field("pcs", description="Unit of measurement (pcs, kg, meters, etc.)")
    price: float = Field(..., description="Unit price in transaction currency")

class CustomsInvoiceSchema(BaseModel):
    seller_name: str = Field(..., description="Name of the selling company (Vendor)")
    buyer_name: str = Field(..., description="Name of the buying company (Importer)")
    incoterms: str = Field("FCA Shenzhen", description="Incoterms delivery condition")
    items: List[InvoiceItemSchema] = Field(..., description="List of invoiced goods")

class SupplyAgreementSchema(BaseModel):
    contract_no: str = Field(..., description="Unique agreement contract number")
    contract_date: str = Field(..., description="Date of contract signing")
    seller_name: str = Field(..., description="Selling company name")
    buyer_name: str = Field(..., description="Buying company name")
    incoterms: str = Field("DDP Almaty", description="Incoterms delivery condition")

class DocumentGenerator:
    """
    Generates formal trade documents:
    - Invoices & Specifications (Excel / .xlsx)
    - Supply Agreements / Договоры поставки (Word / .docx)
    - Analytical party tables and Customs Declarations summaries (PDF)
    """
    
    @staticmethod
    def generate_invoice_excel(data: Union[CustomsInvoiceSchema, Dict[str, Any]], output_path: str) -> str:
        """
        Generates a standard commercial invoice in Excel (.xlsx) format using CustomsInvoiceSchema.
        """
        if isinstance(data, dict):
            # Support legacy dict structures
            resolved_items = []
            for item in data.get("items", []):
                resolved_items.append(
                    InvoiceItemSchema(
                        name=item.get("name", "Sample Goods"),
                        hs_code=item.get("hs_code", "8543709000"),
                        qty=float(item.get("qty", 100)),
                        unit=item.get("unit", "pcs"),
                        price=float(item.get("price", 10.0))
                    )
                )
            schema = CustomsInvoiceSchema(
                seller_name=data.get("seller_name", "Vendor Inc."),
                buyer_name=data.get("buyer_name", "Kazakhstan Importer LLP"),
                incoterms=data.get("incoterms", "FCA Shenzhen"),
                items=resolved_items
            )
        else:
            schema = data

        logger.info(f"Generating commercial invoice Excel at {output_path}")
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "INVOICE"
            
            # Basic invoice template design
            ws['A1'] = "COMMERCIAL INVOICE / ИНВОЙС"
            ws['A1'].font = Font(name="Arial", size=16, bold=True)
            
            ws['A3'] = "Seller (Продавец):"
            ws['B3'] = schema.seller_name
            
            ws['A4'] = "Buyer (Покупатель):"
            ws['B4'] = schema.buyer_name
            
            ws['A5'] = "Incoterms:"
            ws['B5'] = schema.incoterms
            
            # Headers
            headers = ["No", "Description of Goods", "HS Code", "Qty", "Unit", "Price", "Amount"]
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=8, column=col_idx, value=header)
                cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
                cell.alignment = Alignment(horizontal="center")
            
            # Simple item loop
            row_idx = 9
            for idx, item in enumerate(schema.items, 1):
                ws.cell(row=row_idx, column=1, value=idx)
                ws.cell(row=row_idx, column=2, value=item.name)
                ws.cell(row=row_idx, column=3, value=item.hs_code)
                ws.cell(row=row_idx, column=4, value=item.qty)
                ws.cell(row=row_idx, column=5, value=item.unit)
                ws.cell(row=row_idx, column=6, value=item.price)
                ws.cell(row=row_idx, column=7, value=item.qty * item.price)
                row_idx += 1
            
            # Save file
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            wb.save(output_path)
            return output_path
        except ImportError:
            logger.warning("openpyxl not installed, writing basic dummy text instead")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"Invoice Schema: {schema.model_dump_json()}")
            return output_path

    @staticmethod
    def generate_contract_word(data: Union[SupplyAgreementSchema, Dict[str, Any]], output_path: str) -> str:
        """
        Generates a standard foreign trade supply agreement in Word (.docx) format using SupplyAgreementSchema.
        """
        if isinstance(data, dict):
            schema = SupplyAgreementSchema(
                contract_no=data.get("contract_no", "2026/01"),
                contract_date=data.get("contract_date", "27 мая 2026 г."),
                seller_name=data.get("seller_name", "Vendor Inc."),
                buyer_name=data.get("buyer_name", "Kazakhstan Importer LLP"),
                incoterms=data.get("incoterms", "DDP Almaty")
            )
        else:
            schema = data

        logger.info(f"Generating supply contract Word document at {output_path}")
        try:
            import docx
            from docx import Document
            
            doc = docx.Document()
            doc.add_heading("ДОГОВОР ПОСТАВКИ № " + schema.contract_no, level=1)
            
            p = doc.add_paragraph()
            p.add_run("г. Алматы\t\t\t\t\tДата: ").bold = True
            p.add_run(schema.contract_date)
            
            doc.add_heading("1. ПРЕДМЕТ ДОГОВОРА", level=2)
            doc.add_paragraph(
                f"Продавец обязуется поставить, а Покупатель принять и оплатить товар в соответствии "
                f"со спецификациями к настоящему договору на условиях {schema.incoterms}."
            )
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            doc.save(output_path)
            return output_path
        except ImportError:
            logger.warning("docx not installed, writing basic dummy text instead")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"Contract Schema: {schema.model_dump_json()}")
            return output_path