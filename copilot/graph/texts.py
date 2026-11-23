"""Fixed replies written by code (no model involved), in English and Bulgarian."""

TEXTS = {
    "en": {
        "capabilities": ("I can answer questions about the e-invoicing rules of Valdoria, Kestria and Orlavia and "
                         "the common invoice model (for a given date, with citations), validate and explain an "
                         "attached UBL invoice, and compare the countries."),
        "out_of_scope": "That is outside what I can help with: my documents cover only Valdoria, Kestria, Orlavia "
                        "and their common invoice model.",
        "clarify_attachment": "Please attach the UBL invoice you want me to check (Attach invoice), then ask again.",
        "clarify_countries": "Which countries should I compare? Name at least two of Valdoria, Kestria and Orlavia.",
        "attachment_missing": "I could not find the attached invoice any more. Please attach it again.",
        "not_in_documents": "This is not in the documents I have for {dates}. A national law, technical "
                            "specification or FAQ of the country would be the place to look.",
        "ungrounded": "I found related passages but could not give an answer that rests on them, so I will not "
                      "guess. Please rephrase the question or name the country and date.",
        "valid": "The rule engine found no problems. It checked {count} rules ({sets}) for a {country} "
                 "{transaction_type} invoice, selected for {date}.",
        "unreadable": "The file could not be read as a UBL 2.1 invoice: {reason} {fix}",
        "compare_summary": "Comparison of {countries} on {date}: {cited} of {total} cells rest on a cited "
                           "passage; the others are not specified in the documents.",
        "not_specified": "Not specified in the documents.",
        "cause": "Likely cause",
        "fix": "Fix",
    },
    "bg": {
        "capabilities": ("Мога да отговарям на въпроси за правилата за електронни фактури във Валдория, Кестрия и "
                         "Орлавия и за общия модел на фактурата (към дадена дата, с цитати), да проверя и обясня "
                         "прикачена UBL фактура и да сравня държавите."),
        "out_of_scope": "Това е извън това, с което мога да помогна: документите ми покриват само Валдория, "
                        "Кестрия, Орлавия и общия им модел на фактурата.",
        "clarify_attachment": "Моля, прикачете UBL фактурата, която да проверя (Attach invoice), и попитайте отново.",
        "clarify_countries": "Кои държави да сравня? Посочете поне две от Валдория, Кестрия и Орлавия.",
        "attachment_missing": "Не намирам прикачената фактура. Моля, прикачете я отново.",
        "not_in_documents": "Това не е в документите, с които разполагам за {dates}. Би трябвало да е в закон, "
                            "техническа спецификация или ЧЗВ на съответната държава.",
        "ungrounded": "Намерих свързани откъси, но не успях да дам отговор, който да се опира на тях, затова няма "
                      "да гадая. Моля, задайте въпроса по-конкретно (държава и дата).",
        "valid": "Машината за правила не откри проблеми. Проверени са {count} правила ({sets}) за фактура "
                 "{country} {transaction_type}, избрани към {date}.",
        "unreadable": "Файлът не може да се прочете като UBL 2.1 фактура: {reason} {fix}",
        "compare_summary": "Сравнение на {countries} към {date}: {cited} от {total} клетки се опират на цитиран "
                           "откъс; останалите не са посочени в документите.",
        "not_specified": "Не е посочено в документите.",
        "cause": "Вероятна причина",
        "fix": "Поправка",
    },
}


def text(lang: str, key: str, **values) -> str:
    return TEXTS.get(lang, TEXTS["en"])[key].format(**values)
