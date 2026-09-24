import fitz


def extract_pdf_text(file_path):

    document = fitz.open(file_path)

    pages = []

    for page_number, page in enumerate(document):

        text = page.get_text()

        pages.append({
            "page": page_number + 1,
            "text": text
        })

    document.close()

    return pages


if __name__ == "__main__":

    file_path = "document_processing\samples\invoice_2_bluepeak_it_services.pdf"
    pages = extract_pdf_text(file_path)

    for page in pages:
        print(f"\n--- Page {page['page']} ---")
        print(page["text"])