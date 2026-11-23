"""Safe parsing of uploaded UBL invoices.

The parser never resolves entities, never loads a DTD and never touches the network; a document with a DOCTYPE is
refused outright (no legitimate UBL invoice needs one), which also stops "billion laughs" style entity expansion.
"""
from lxml import etree

UBL_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS = {
    "inv": UBL_INVOICE,
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


class InvoiceXMLError(ValueError):
    """The upload is not a UBL 2.1 invoice we are willing to read (reported as finding XML-00)."""


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                           remove_comments=True, remove_pis=True)


def parse_invoice(data: bytes, max_kb: int) -> etree._ElementTree:
    if len(data) > max_kb * 1024:
        raise InvoiceXMLError(f"The file is larger than {max_kb} KB.")
    try:
        tree = etree.ElementTree(etree.fromstring(data, _parser()))
    except etree.XMLSyntaxError as exc:
        raise InvoiceXMLError(f"The file is not well-formed XML: {exc.msg}") from None
    # Checked on the parsed tree, not the bytes, so a UTF-16 file cannot hide its DOCTYPE. Even if it got this far,
    # the parser has not expanded or fetched anything.
    if tree.docinfo.doctype or tree.docinfo.internalDTD is not None:
        raise InvoiceXMLError("Document type declarations (DOCTYPE) are not allowed in an invoice.")
    root = tree.getroot()
    if root.tag != f"{{{UBL_INVOICE}}}Invoice":
        raise InvoiceXMLError(f"The root element must be a UBL 2.1 Invoice, not '{etree.QName(root).localname}'.")
    return tree
