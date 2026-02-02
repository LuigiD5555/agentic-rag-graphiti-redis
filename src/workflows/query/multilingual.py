"""Multilingual support for RAG system."""
from typing import Optional
from langdetect import detect, LangDetectException
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class LanguageDetector:
    """Detects and manages language context for RAG queries."""

    # Language code mapping to full names
    LANGUAGE_NAMES = {
        'en': 'English',
        'es': 'Spanish',
        'zh-cn': 'Chinese (Simplified)',
        'zh-tw': 'Chinese (Traditional)',
        'ja': 'Japanese',
        'ko': 'Korean',
        'ru': 'Russian',
        'ar': 'Arabic',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'pt': 'Portuguese',
        'hi': 'Hindi',
        'tr': 'Turkish',
        'vi': 'Vietnamese',
        'th': 'Thai',
    }

    # System prompts for different languages
    SYSTEM_PROMPTS = {
        'en': """You are a helpful assistant that answers questions based on the provided context.

Guidelines:
- Answer the question using ONLY the information from the provided context.
- If the context doesn't contain enough information to answer, say so clearly.
- Provide detailed, well-structured answers; prefer depth over brevity.
- Use bullet points or short sections when helpful.
- When multiple relevant sources exist, synthesize them.
- Cite sources when relevant (mention document names/paths).
- If multiple sources provide conflicting information, acknowledge this.
""",
        'es': """Eres un asistente útil que responde preguntas con base en el contexto proporcionado.

Guías:
- Responde la pregunta usando SOLO la información del contexto proporcionado.
- Si el contexto no contiene suficiente información para responder, dilo claramente.
- Ofrece respuestas detalladas y bien estructuradas; prioriza la profundidad sobre la brevedad.
- Usa viñetas o secciones cortas cuando sea útil.
- Cuando haya varias fuentes relevantes, sintetízalas.
- Cita fuentes cuando sea relevante (menciona nombres/rutas de documentos).
- Si varias fuentes aportan información contradictoria, reconócelo.
""",
        'zh-cn': """你是一个有用的助手，根据提供的上下文回答问题。

指南：
- 仅使用提供的上下文中的信息回答问题。
- 如果上下文不包含足够的信息来回答，请明确说明。
- 提供详细且结构良好的回答，优先深度而非简短。
- 需要时使用要点或简短小节。
- 当有多个相关来源时，进行综合总结。
- 在相关时引用来源（提及文档名称/路径）。
- 如果多个来源提供相互矛盾的信息，请承认这一点。
""",
        'ja': """あなたは提供されたコンテキストに基づいて質問に答える役立つアシスタントです。

ガイドライン：
- 提供されたコンテキストの情報のみを使用して質問に答えてください。
- コンテキストに十分な情報が含まれていない場合は、明確に述べてください。
- 詳細で構造化された回答を提供し、簡潔さより深さを優先してください。
- 必要に応じて箇条書きや短いセクションを使用してください。
- 複数の関連ソースがある場合は統合してください。
- 関連する場合はソースを引用してください（ドキュメント名/パスを記載）。
- 複数のソースが矛盾する情報を提供している場合は、それを認めてください。
""",
        'ko': """당신은 제공된 맥락을 기반으로 질문에 답하는 유용한 도우미입니다.

지침:
- 제공된 맥락의 정보만을 사용하여 질문에 답하십시오.
- 맥락에 답변하기에 충분한 정보가 없으면 명확하게 말하십시오.
- 자세하고 구조적인 답변을 제공하고, 간결함보다 깊이를 우선하세요.
- 필요할 때 글머리표나 짧은 섹션을 사용하세요.
- 관련 출처가 여러 개라면 통합하여 요약하세요.
- 관련이 있을 때 출처를 인용하십시오(문서 이름/경로 언급).
- 여러 출처가 상충되는 정보를 제공하는 경우 이를 인정하십시오.
""",
        'ru': """Вы полезный помощник, который отвечает на вопросы на основе предоставленного контекста.

Рекомендации:
- Отвечайте на вопрос, используя ТОЛЬКО информацию из предоставленного контекста.
- Если контекст не содержит достаточно информации для ответа, четко укажите это.
- Давайте подробные и структурированные ответы, отдавая приоритет глубине, а не краткости.
- При необходимости используйте пункты или короткие разделы.
- Если есть несколько релевантных источников, синтезируйте их.
- Цитируйте источники, когда это уместно (упоминайте имена/пути документов).
- Если несколько источников предоставляют противоречивую информацию, признайте это.
""",
        'ar': """أنت مساعد مفيد يجيب على الأسئلة بناءً على السياق المقدم.

إرشادات:
- أجب على السؤال باستخدام المعلومات الواردة في السياق المقدم فقط.
- إذا كان السياق لا يحتوي على معلومات كافية للإجابة، فقل ذلك بوضوح.
- قدّم إجابات مفصّلة ومنظمة، وفضّل العمق على الإيجاز.
- استخدم النقاط أو الأقسام القصيرة عند الحاجة.
- عند وجود عدة مصادر ذات صلة، قم بدمجها.
- استشهد بالمصادر عند الاقتضاء (اذكر أسماء/مسارات المستندات).
- إذا قدمت مصادر متعددة معلومات متضاربة، فاعترف بذلك.
""",
        'fr': """Vous êtes un assistant utile qui répond aux questions en fonction du contexte fourni.

Directives :
- Répondez à la question en utilisant UNIQUEMENT les informations du contexte fourni.
- Si le contexte ne contient pas suffisamment d'informations pour répondre, dites-le clairement.
- Fournissez des réponses détaillées et structurées ; privilégiez la profondeur plutôt que la brièveté.
- Utilisez des puces ou de courtes sections lorsque c'est utile.
- Lorsqu'il existe des sources pertinentes multiples, synthétisez-les.
- Citez les sources le cas échéant (mentionnez les noms/chemins de documents).
- Si plusieurs sources fournissent des informations contradictoires, reconnaissez-le.
""",
        'de': """Sie sind ein hilfreicher Assistent, der Fragen basierend auf dem bereitgestellten Kontext beantwortet.

Richtlinien:
- Beantworten Sie die Frage NUR mit den Informationen aus dem bereitgestellten Kontext.
- Wenn der Kontext nicht genügend Informationen enthält, um zu antworten, sagen Sie dies klar.
- Geben Sie ausführliche, gut strukturierte Antworten; bevorzugen Sie Tiefe gegenüber Kürze.
- Verwenden Sie bei Bedarf Aufzählungspunkte oder kurze Abschnitte.
- Wenn mehrere relevante Quellen vorhanden sind, fassen Sie sie zusammen.
- Zitieren Sie Quellen, wenn relevant (erwähnen Sie Dokumentnamen/-pfade).
- Wenn mehrere Quellen widersprüchliche Informationen liefern, erkennen Sie dies an.
""",
        'pt': """Você é um assistente útil que responde perguntas com base no contexto fornecido.

Diretrizes:
- Responda à pergunta usando APENAS as informações do contexto fornecido.
- Se o contexto não contiver informações suficientes para responder, diga isso claramente.
- Forneça respostas detalhadas e bem estruturadas; priorize a profundidade em vez da brevidade.
- Use marcadores ou seções curtas quando útil.
- Quando houver várias fontes relevantes, sintetize-as.
- Cite as fontes quando relevante (mencione nomes/caminhos de documentos).
- Se várias fontes fornecerem informações conflitantes, reconheça isso.
""",
    }

    @staticmethod
    def detect_language(text: str) -> str:
        """Detect the language of the given text.

        Args:
            text: Input text to detect language for.

        Returns:
            ISO 639-1 language code (e.g., 'en', 'es', 'zh-cn', 'ja', 'ko', 'ru').
        """
        if not text or not text.strip():
            return 'en'  # Default to English

        try:
            lang_code = detect(text)
            log.debug("Detected language: %s for text: %s", lang_code, text[:50])
            return lang_code
        except LangDetectException as e:
            log.warning("Failed to detect language: %s. Defaulting to English.", e)
            return 'en'

    @classmethod
    def get_system_prompt(cls, language_code: str) -> str:
        """Get system prompt for the detected language.

        Args:
            language_code: ISO 639-1 language code.

        Returns:
            System prompt in the appropriate language.
        """
        # Try exact match first
        if language_code in cls.SYSTEM_PROMPTS:
            return cls.SYSTEM_PROMPTS[language_code]

        # Handle Chinese variants
        if language_code.startswith('zh'):
            return cls.SYSTEM_PROMPTS.get('zh-cn', cls.SYSTEM_PROMPTS['en'])

        # Default to English
        log.debug("No system prompt for language %s, using English", language_code)
        return cls.SYSTEM_PROMPTS['en']

    @classmethod
    def get_language_name(cls, language_code: str) -> str:
        """Get full language name from code.

        Args:
            language_code: ISO 639-1 language code.

        Returns:
            Full language name.
        """
        return cls.LANGUAGE_NAMES.get(language_code, f"Unknown ({language_code})")

    @classmethod
    def add_language_instruction(cls, system_prompt: str, language_code: str) -> str:
        """Add explicit instruction to respond in the detected language.

        Args:
            system_prompt: Base system prompt.
            language_code: Detected language code.

        Returns:
            Enhanced system prompt with language instruction.
        """
        if language_code == 'en':
            return system_prompt  # No need for explicit instruction in English

        language_name = cls.get_language_name(language_code)
        language_instructions = {
            'es': f"\n\nIMPORTANT: Always respond in Spanish.",
            'zh-cn': f"\n\n重要提示：始终用中文回答。",
            'ja': f"\n\n重要：常に日本語で回答してください。",
            'ko': f"\n\n중요: 항상 한국어로 답변하십시오.",
            'ru': f"\n\nВАЖНО: Всегда отвечайте на русском языке.",
            'ar': f"\n\nمهم: أجب دائمًا باللغة العربية.",
            'fr': f"\n\nIMPORTANT : Répondez TOUJOURS en français.",
            'de': f"\n\nWICHTIG: Antworten Sie IMMER auf Deutsch.",
            'pt': f"\n\nIMPORTANTE: Responda SEMPRE em português.",
        }

        instruction = language_instructions.get(
            language_code,
            f"\n\nIMPORTANT: Always respond in {language_name}."
        )

        return system_prompt + instruction


__all__ = ['LanguageDetector']
