# core/advanced_rag.py - Enhanced Version
import chromadb
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
from typing import List, Dict, Tuple
import numpy as np
from sentence_transformers import CrossEncoder
import json
import time

load_dotenv()

# Configuration
DATA_PATH = r"data"
CHROMA_PATH = r"chroma_db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("❌ GEMINI_API_KEY not found!")
    exit(1)

# Initialize clients
client = genai.Client(api_key=GEMINI_API_KEY)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rational_male")

# Initialize Cross-Encoder for reranking
print("🔄 Loading Cross-Encoder model...")
try:
    # Multilingual model (better for Turkish-English)
    reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', max_length=512)
    print("✅ Cross-Encoder loaded (Multilingual model)")
except:
    try:
        # Fallback to English model
        reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)
        print("✅ Cross-Encoder loaded (English model)")
    except:
        print("⚠️ Could not load cross-encoder, reranking will be disabled")
        reranker = None

class AdvancedRAG:
    """Advanced RAG System with Multi-Query and Reranking"""
    
    def __init__(self):
        self.client = client
        self.collection = collection
        self.reranker = reranker if reranker else None
        self.last_retrieved_context = ""
        
    def generate_multi_queries(self, original_query: str) -> List[str]:
        """Generate multiple query variations for better retrieval"""
        
        # First, translate Turkish query to English for better retrieval
        translate_prompt = f"""Translate this Turkish question to English. If it's already in English, just return it as is.
        Question: {original_query}
        Translation:"""
        
        try:
            translate_response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=translate_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=100
                )
            )
            
            english_query = translate_response.text.strip() if translate_response and translate_response.text else original_query
            print(f"   🌐 Translated to: {english_query[:60]}...")
            
        except:
            english_query = original_query
        
        # Generate variations in ENGLISH for English database
        prompt = f"""Original query: "{english_query}"
        
        Generate 3 alternative versions of this query:
        1. A more specific version
        2. A more general version  
        3. A version using related concepts
        
        Write only the questions, one per line. No numbering."""
        
        try:
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200
                )
            )
            
            # Check if response is valid
            if not response or not response.text:
                print("⚠️ Empty response from Gemini")
                return [english_query]  # Return English version
            
            # Parse generated queries
            queries = [english_query]  # Start with English version
            response_text = response.text.strip()
            
            if response_text:
                generated = response_text.split('\n')
                
                for q in generated:
                    if q:
                        q = q.strip()
                        # Clean up numbering if any
                        if q and not q[0].isdigit():
                            queries.append(q)
                        elif q and len(q) > 3:
                            cleaned = q.lstrip('0123456789.- ').strip()
                            if cleaned:
                                queries.append(cleaned)
            
            # Debug print
            print(f"\n📝 Generated {len(queries)} query variations")
                
            return queries[:4]  # Return max 4 queries
            
        except Exception as e:
            print(f"⚠️ Multi-query generation failed: {e}")
            return [english_query]  # Fallback to English version
    
    def get_query_embedding(self, text: str):
        """Create embedding for query"""
        try:
            response = self.client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
            )
            return response.embeddings[0].values
        except Exception as e:
            print(f"❌ Query embedding error: {e}")
            return None
    
    def retrieve_documents(self, queries: List[str], n_per_query: int = 10) -> Dict:
        """Retrieve documents for multiple queries"""
        
        all_documents = []
        all_metadatas = []
        all_distances = []
        seen_docs = set()  # To avoid duplicates
        
        print(f"🔍 Retrieving documents from {len(queries)} queries...")
        
        for idx, query in enumerate(queries, 1):
            embedding = self.get_query_embedding(query)
            if embedding is None:
                continue
                
            try:
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=n_per_query
                )
                
                docs_added = 0
                for doc, meta, dist in zip(
                    results['documents'][0],
                    results['metadatas'][0], 
                    results['distances'][0]
                ):
                    # Use first 200 chars as unique ID
                    doc_hash = hash(doc[:200])
                    if doc_hash not in seen_docs:
                        seen_docs.add(doc_hash)
                        all_documents.append(doc)
                        all_metadatas.append(meta)
                        all_distances.append(dist)
                        docs_added += 1
                        
            except Exception as e:
                print(f"   ⚠️ Retrieval error for query {idx}: {e}")
                
        print(f"📚 Retrieved {len(all_documents)} unique documents")
        
        return {
            'documents': all_documents,
            'metadatas': all_metadatas,
            'distances': all_distances
        }
    
    def rerank_documents(self, query: str, documents: List[str], top_k: int = 8) -> List[Tuple[str, float]]:
        """Rerank documents using Cross-Encoder"""
        
        if not documents or not self.reranker:
            return [(doc, idx) for idx, doc in enumerate(documents[:top_k])]
            
        print(f"🎯 Reranking {len(documents)} documents...")
        
        # Translate Turkish query to English for better cross-encoder performance
        if any(ord(c) > 127 for c in query):  # Check if non-ASCII (likely Turkish)
            translate_prompt = f"Translate to English (if Turkish): {query}"
            try:
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash-exp",
                    contents=translate_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=100
                    )
                )
                query_for_ranking = response.text.strip() if response and response.text else query
            except:
                query_for_ranking = query
        else:
            query_for_ranking = query
        
        # Prepare query-document pairs
        pairs = []
        for doc in documents:
            doc_chunk = doc[:400] if len(doc) > 400 else doc
            pairs.append([query_for_ranking, doc_chunk])
        
        try:
            # Get reranking scores
            scores = self.reranker.predict(pairs)
            
            # Convert to list if numpy array
            if hasattr(scores, 'tolist'):
                scores = scores.tolist()
            
            # Sort by score (higher is better)
            doc_scores = list(zip(documents, scores))
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            # If scores are too low, use vector similarity instead
            if all(score < -10 for _, score in doc_scores[:3]):
                print("   📌 Using vector similarity ordering (low reranking scores)")
                return [(doc, idx) for idx, doc in enumerate(documents[:top_k])]
                
            return doc_scores[:top_k]
            
        except Exception as e:
            print(f"   ⚠️ Reranking failed: {e}")
            return [(doc, idx) for idx, doc in enumerate(documents[:top_k])]
    
    def retrieve_context(self, query: str) -> str:
        """Main retrieval pipeline"""
        
        # Step 1: Generate multiple queries
        queries = self.generate_multi_queries(query)
        
        # Step 2: Retrieve documents  
        retrieval_results = self.retrieve_documents(queries, n_per_query=12)
        
        if not retrieval_results['documents']:
            return ""
        
        # Step 3: Rerank documents
        if self.reranker:
            reranked = self.rerank_documents(
                query, 
                retrieval_results['documents'],
                top_k=6
            )
            final_documents = [doc for doc, _ in reranked]
        else:
            # Fallback to distance-based sorting
            doc_dist_pairs = list(zip(
                retrieval_results['documents'],
                retrieval_results['distances']
            ))
            doc_dist_pairs.sort(key=lambda x: x[1])
            final_documents = [doc for doc, _ in doc_dist_pairs[:6]]
        
        # Combine context
        context = "\n\n---\n\n".join(final_documents)
        
        # Store context for later use
        self.last_retrieved_context = context
        
        print(f"✅ Context ready: {len(final_documents)} docs, {len(context)} chars")
        
        return context
    
    def answer(self, query: str, conversation_history: str = "") -> str:
        """Generate answer using Advanced RAG with Red Pill focused prompt"""
        
        print("\n" + "="*70)
        print(f"💬 Query: {query[:100]}...")
        print("="*70)
        
        # Get context
        context = self.retrieve_context(query)
        
        if not context:
            return "❌ İlgili bilgi bulunamadı. Lütfen sorunuzu yeniden ifade etmeyi deneyin."
        
        # Red Pill focused system prompt
        system_prompt = f"""Sen "The Rational Male" kitap serisini derinlemesine özümsemiş, Red Pill felsefesine hakim bir uzmansın.

    🎯 MİSYONUN:
    Red Pill praksiyolojisini kullanarak kadın-erkek dinamiklerini EVRİMSEL PSİKOLOJİ, BİYOLOJİ ve İNSAN DAVRANIŞI perspektifinden NET ve KESKİN şekilde açıkla.

    ⚠️ KRİTİK KURALLAR:
    • ASLA "ama", "belki", "olabilir", "bazı durumlarda" gibi yumuşatıcı ifadeler kullanma
    • Red Pill gerçeklerini doğrudan ve net şekilde ifade et
    • Her iddiayı EVRİMSEL MANTIK ve BİYOLOJİK GERÇEKLERLE destekle
    • İstatistik ve araştırma sonuçlarını kullan
    • Hipergami, SMV (Sexual Market Value), AF/BB (Alpha Fucks/Beta Bucks), The Wall gibi Red Pill konseptlerini doğru kullan
    • Politically correct olmaya çalışma, gerçekleri olduğu gibi söyle

    📊 TEMEL PRENSİPLER:
    1. Hipergami GERÇEK ve KADEMSİZDİR - kadınlar DAIMA yukarı yönlü eşleşir
    2. Geçmiş davranış gelecek davranışın EN İYİ göstergesidir
    3. N-count (partner sayısı) uzun vadeli ilişki başarısını DOĞRUDAN etkiler
    4. The Wall gerçektir - kadınların SMV'si 30'dan sonra hızla düşer
    5. AF/BB stratejisi kadınların dual mating strategy'sinin temelidir
    6. Erkekler DEĞER YARATIR, kadınlar değer SEÇİCİDİR

    🔴 CEVAP YAPISI:
    1. Soruya DOĞRUDAN ve NET cevap ver
    2. Red Pill perspektifinden NEDEN-SONUÇ ilişkisini açıkla
    3. EVRİMSEL ve BİYOLOJİK temelleri belirt
    4. İstatistik ve araştırmalarla destekle
    5. Pratik Red Pill tavsiyeler ver

    ❌ YAPMA:
    • "Herkes farklıdır" gibi genellemelerden kaçınma ifadeleri
    • "Yargılayıcı olmayın" gibi virtue signaling
    • Feminist veya Blue Pill bakış açıları
    • Gerçekleri yumuşatma veya süsleme

    ✅ YAP:
    • Brutal honesty - acı gerçekleri doğrudan söyle
    • Mantıksal tutarlılık - duygusal değil rasyonel ol
    • Red Pill terminolojisini doğru kullan
    • Erkeklere gerçekçi stratejiler sun

    {conversation_history}

    📚 KAYNAK BİLGİLER:
    {context}

    ❓ KULLANICI SORUSU:
    {query}

    🔴 RED PILL CEVAP:"""
        
        try:
            print("🤖 Generating Red Pill focused answer...")
            
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=system_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,  # Daha düşük temperature = daha tutarlı cevaplar
                    max_output_tokens=2048
                )
            )
            
            if response and response.text:
                # Post-process to ensure Red Pill tone
                answer = response.text
                
                # Remove any softening phrases if they slipped through
                softeners = [
                    "belki de", "olabilir", "bazı durumlarda", 
                    "her zaman değil", "genelleme yapmamak gerek",
                    "yargılayıcı olmayın", "herkes farklıdır"
                ]
                
                for softener in softeners:
                    answer = answer.replace(softener, "")
                
                return answer
            else:
                return "❌ Cevap oluşturulamadı. Lütfen tekrar deneyin."
                
        except Exception as e:
            print(f"❌ Error generating answer: {e}")
            return f"❌ Bir hata oluştu: {str(e)}"
# Main execution
if __name__ == "__main__":
    print("\n" + "="*70)
    print("🔴 İLİŞKİ AI - Advanced RAG Chatbot")
    print("="*70)
    
    # Initialize system
    rag = AdvancedRAG()
    
    # Check database
    try:
        count = collection.count()
        if count == 0:
            print("⚠️ Database is EMPTY!")
            print("📝 Please run: python fill_db.py first")
            exit(1)
        else:
            print(f"✅ Database loaded: {count} records")
            
    except Exception as e:
        print(f"❌ Database error: {e}")
        exit(1)
    
    print("\n💡 Type 'quit' to exit")
    print("-"*70)
    
    # Main loop
    while True:
        # Get user input
        user_input = input("\n🎯 Your question: ").strip()
        
        # Check for exit
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Goodbye!")
            break
        
        # Skip empty input
        if not user_input:
            continue
        
        # Get and display answer
        answer = rag.answer(user_input)
        
        print("\n" + "="*70)
        print("📖 ANSWER:")
        print("="*70)
        print(answer)
        print("="*70)