#!/usr/bin/env python3
"""Test script for multilingual RAG support."""

from src.rag.multilingual import LanguageDetector

# Test queries in different languages
test_queries = {
    'English': "What is the main topic of these documents?",
    'Spanish': "¿Cuál es el tema principal de estos documentos?",
    'Chinese (Simplified)': "这些文档的主要主题是什么？",
    'Japanese': "これらの文書の主なトピックは何ですか？",
    'Korean': "이 문서의 주요 주제는 무엇입니까?",
    'Russian': "Какова основная тема этих документов?",
    'Arabic': "ما هو الموضوع الرئيسي لهذه الوثائق؟",
    'French': "Quel est le sujet principal de ces documents ?",
    'German': "Was ist das Hauptthema dieser Dokumente?",
    'Portuguese': "Qual é o tema principal desses documentos?",
}


def main():
    """Test language detection and prompt generation."""
    detector = LanguageDetector()

    print("=" * 80)
    print("MULTILINGUAL RAG SYSTEM - LANGUAGE DETECTION TEST")
    print("=" * 80)
    print()

    for expected_lang, query in test_queries.items():
        print(f"Expected Language: {expected_lang}")
        print(f"Query: {query}")
        print("-" * 80)

        # Detect language
        detected_code = detector.detect_language(query)
        detected_name = detector.get_language_name(detected_code)

        print(f"Detected Code: {detected_code}")
        print(f"Detected Name: {detected_name}")

        # Get system prompt
        system_prompt = detector.get_system_prompt(detected_code)
        print(f"\nSystem Prompt Preview (first 200 chars):")
        print(f"{system_prompt[:200]}...")

        # Get with language instruction
        enhanced_prompt = detector.add_language_instruction(system_prompt, detected_code)
        if enhanced_prompt != system_prompt:
            print(f"\nLanguage Instruction Added:")
            print(f"{enhanced_prompt[len(system_prompt):].strip()}")

        print()
        print("=" * 80)
        print()


if __name__ == "__main__":
    main()