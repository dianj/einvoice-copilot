"""Fixed replies written by code (no model involved), in English and Bulgarian."""

TEXTS = {
    "en": {
        "capabilities": ("I can answer questions about the e-invoicing rules of Valdoria, Kestria and Orlavia and "
                         "the common invoice model (for a given date, with citations), validate and explain an "
                         "attached UBL invoice, compare the countries, and draft a requirement that becomes a "
                         "ServiceNow ticket once you approve it."),
        "out_of_scope": "That is outside what I can help with: my documents cover only Valdoria, Kestria, Orlavia "
                        "and their common invoice model.",
        "clarify_attachment": "Please attach the UBL invoice you want me to check (Attach invoice), then ask again.",
        "clarify_countries": "Which countries should I compare? Name at least two of Valdoria, Kestria and Orlavia.",
        "attachment_missing": "I could not find the attached invoice any more. Please attach it again.",
        "no_skip_validation": "The check cannot be skipped: the result below is the rule engine's.",
        "more_options": "I can also check an attached invoice, compare the countries or draft a requirement: tell me "
                        "which.",
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
        "clarify_draft": "Which change should the requirement cover? Name the country and the rule or obligation, "
                         "e.g. \"Draft a requirement for the Orlavia reporting deadline\".",
        "draft_no_sources": "I found no passage in the documents to base such a requirement on, so I did not draft "
                            "one. Name the country and the rule or obligation more precisely.",
        "draft_failed": "I could not produce a requirement that rests on the documents, so none is shown. Please "
                        "name the country and the obligation more precisely.",
        "draft_heading": "Draft requirement",
        "draft_meta": "Country: {country} · effective {date} · priority {priority}",
        "user_story": "User story",
        "acceptance": "Acceptance criteria",
        "rules": "Validation rules",
        "offer_ticket": "Shall I create a ServiceNow ticket for it? Use Create ticket (or say so); you can edit or "
                        "reject the draft before anything is created.",
        "approval_needed": "Please review the draft: approve it (edits allowed) or reject it. No ticket is created "
                           "without your approval.",
        "ticket_rejected": "Not created: the draft was not approved. It stays in this conversation if you want a "
                           "ticket later.",
        "ticket_not_approved": "Not created: this draft has no approval.",
        "ticket_failed": "The draft is approved, but the ticket could not be created: {reason} Nothing was created; "
                         "ask again for the ticket when the system is back.",
        "ticket_created": "Created ServiceNow ticket {number} for the approved draft.",
        "ticket_exists": "A ticket for this approved draft exists already: {number}. Nothing new was created.",
        "warn_bad_date": "The effective date \"{value}\" is not a date: check it before approving.",
        "warn_unverified_date": "The effective date {value} does not appear in the cited passages: check it "
                                "before approving.",
        "warn_no_date": "The passages give no effective date: add one before approving if it is known.",
        "clarify_intent": "Just to be sure: do you want me to {options}?",
        "or": ", or ",
        "intent_question": "answer a question about the rules",
        "intent_validate": "check the attached invoice",
        "intent_compare": "compare the countries",
        "intent_draft_requirement": "draft a requirement",
        "intent_create_ticket": "create the ticket for the draft",
        "intent_out_of_scope": "help with something outside these documents",
        "approval_unclear": "I did not take that as a clear approval, so nothing was created. Use Approve or Reject "
                            "on the card, or answer yes or no.",
    },
    "bg": {
        "capabilities": ("Мога да отговарям на въпроси за правилата за електронни фактури във Валдория, Кестрия и "
                         "Орлавия и за общия модел на фактурата (към дадена дата, с цитати), да проверя и обясня "
                         "прикачена UBL фактура, да сравня държавите и да изготвя изискване, което става ticket в "
                         "ServiceNow след ваше одобрение."),
        "out_of_scope": "Това е извън това, с което мога да помогна: документите ми покриват само Валдория, "
                        "Кестрия, Орлавия и общия им модел на фактурата.",
        "clarify_attachment": "Моля, прикачете UBL фактурата, която да проверя (Attach invoice), и попитайте отново.",
        "clarify_countries": "Кои държави да сравня? Посочете поне две от Валдория, Кестрия и Орлавия.",
        "attachment_missing": "Не намирам прикачената фактура. Моля, прикачете я отново.",
        "no_skip_validation": "Проверката не може да се пропусне: по-долу е резултатът от машината за правила.",
        "more_options": "Мога също да проверя прикачена фактура, да сравня страните или да изготвя изискване: "
                        "кажете кое.",
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
        "clarify_draft": "Каква промяна да покрива изискването? Посочете държавата и правилото или задължението, "
                         "напр. \"Изготви изискване за срока за докладване в Орлавия\".",
        "draft_no_sources": "Не намерих откъс в документите, на който да се опре такова изискване, затова не съм "
                            "го изготвил. Посочете по-точно държавата и правилото или задължението.",
        "draft_failed": "Не успях да изготвя изискване, което да се опира на документите, затова не показвам "
                        "такова. Посочете по-точно държавата и задължението.",
        "draft_heading": "Чернова на изискване",
        "draft_meta": "Държава: {country} · в сила от {date} · приоритет {priority}",
        "user_story": "Потребителска история",
        "acceptance": "Критерии за приемане",
        "rules": "Правила за валидиране",
        "offer_ticket": "Да създам ли ticket в ServiceNow? Използвайте Create ticket (или го напишете); преди да се "
                        "създаде нещо, можете да редактирате или отхвърлите черновата.",
        "approval_needed": "Моля, прегледайте черновата: одобрете я (може с редакции) или я отхвърлете. Без ваше "
                           "одобрение ticket не се създава.",
        "ticket_rejected": "Не е създаден: черновата не е одобрена. Тя остава в разговора, ако по-късно искате "
                           "ticket.",
        "ticket_not_approved": "Не е създаден: тази чернова няма одобрение.",
        "ticket_failed": "Черновата е одобрена, но ticket не можа да се създаде: {reason} Нищо не е създадено; "
                         "поискайте ticket отново, когато системата работи.",
        "ticket_created": "Създаден е ticket {number} в ServiceNow за одобрената чернова.",
        "ticket_exists": "За тази одобрена чернова вече има ticket: {number}. Нищо ново не е създадено.",
        "warn_bad_date": "Датата на влизане в сила \"{value}\" не е дата: проверете я, преди да одобрите.",
        "warn_unverified_date": "Датата {value} не се среща в цитираните откъси: проверете я, преди да одобрите.",
        "warn_no_date": "Откъсите не посочват дата на влизане в сила: добавете я, преди да одобрите, ако е известна.",
        "clarify_intent": "За да съм сигурен: искате ли да {options}?",
        "or": ", или да ",
        "intent_question": "отговоря на въпрос за правилата",
        "intent_validate": "проверя прикачената фактура",
        "intent_compare": "сравня държавите",
        "intent_draft_requirement": "изготвя изискване",
        "intent_create_ticket": "създам ticket за черновата",
        "intent_out_of_scope": "помогна с нещо извън тези документи",
        "approval_unclear": "Не приех това като ясно одобрение, затова нищо не е създадено. Използвайте Approve или "
                            "Reject на картата или отговорете с да или не.",
    },
}


def text(lang: str, key: str, **values) -> str:
    return TEXTS.get(lang, TEXTS["en"])[key].format(**values)
