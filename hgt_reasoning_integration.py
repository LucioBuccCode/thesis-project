"""
hgt_reasoning_integration.py
Modulo per integrare correttamente gli embeddings HGT nel processo di reasoning
DA AGGIUNGERE nella cartella ie_hgt_hgt_pipeline_claude/
"""

import torch
import torch.nn.functional as F
from typing import Dict, List, Tuple, Optional
import numpy as np
from sentence_transformers import SentenceTransformer
import json
import logging

logger = logging.getLogger(__name__)

class HGTReasoningIntegrator:
    """
    Integra gli embeddings HGT nel processo di reasoning multi-hop
    invece di buttarli via!
    """
    
    def __init__(self, device="cuda"):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        
    def extract_relevant_knowledge(
        self,
        hgt_embeddings: Dict[str, torch.Tensor],
        question: str,
        triples: List[Dict],
        graph_data,
        metadata: Dict,
        top_k: int = 10
    ) -> Dict:
        """
        Usa gli embeddings HGT per estrarre conoscenza rilevante
        
        Returns:
            Dict con:
            - relevant_entities: entità più rilevanti secondo HGT
            - relevant_triples: triple più rilevanti
            - reasoning_paths: percorsi di reasoning identificati
            - attention_scores: punteggi di attenzione per interpretabilità
        """
        
        # 1. Codifica la domanda
        question_emb = torch.tensor(
            self.encoder.encode(question), 
            device=self.device
        )
        
        # 2. Trova entità rilevanti usando embeddings HGT
        relevant_entities = self._find_relevant_entities(
            hgt_embeddings, question_emb, metadata, top_k
        )
        
        # 3. Trova triple rilevanti basate sugli embeddings
        relevant_triples = self._find_relevant_triples(
            triples, relevant_entities, hgt_embeddings, question_emb
        )
        
        # 4. Estrai pattern di reasoning dagli embeddings
        reasoning_patterns = self._extract_reasoning_patterns(
            hgt_embeddings, relevant_entities
        )
        
        # 5. Identifica percorsi multi-hop
        reasoning_paths = self._identify_multihop_paths(
            relevant_entities, relevant_triples, hgt_embeddings
        )
        
        return {
            "relevant_entities": relevant_entities,
            "relevant_triples": relevant_triples,
            "reasoning_patterns": reasoning_patterns,
            "reasoning_paths": reasoning_paths,
            "confidence_scores": self._calculate_confidence_scores(
                relevant_entities, relevant_triples, reasoning_paths
            )
        }
    
    def _find_relevant_entities(
        self,
        embeddings: Dict[str, torch.Tensor],
        question_emb: torch.Tensor,
        metadata: Dict,
        top_k: int
    ) -> List[Dict]:
        """
        Trova le entità più rilevanti usando similarità coseno con embeddings HGT
        """
        relevant = []
        
        # Per ogni tipo di nodo
        for node_type, node_embeddings in embeddings.items():
            if len(node_embeddings) == 0:
                continue
            
            # Calcola similarità con la domanda
            similarities = F.cosine_similarity(
                node_embeddings,
                question_emb.unsqueeze(0).expand(node_embeddings.shape[0], -1),
                dim=1
            )
            
            # Prendi top-k
            k = min(top_k, len(similarities))
            top_scores, top_indices = torch.topk(similarities, k)
            
            # Mappa indici a entità reali
            if node_type == "entity":
                entities = metadata.get("entities", [])
            elif node_type == "wikidata":
                entities = metadata.get("qids", [])
            else:
                entities = []
            
            for idx, score in zip(top_indices.cpu().numpy(), top_scores.cpu().numpy()):
                if idx < len(entities):
                    relevant.append({
                        "type": node_type,
                        "entity": entities[idx],
                        "index": int(idx),
                        "score": float(score),
                        "embedding": node_embeddings[idx].cpu().numpy().tolist()
                    })
        
        # Ordina per score
        relevant.sort(key=lambda x: x["score"], reverse=True)
        
        return relevant[:top_k]
    
    def _find_relevant_triples(
        self,
        triples: List[Dict],
        relevant_entities: List[Dict],
        embeddings: Dict[str, torch.Tensor],
        question_emb: torch.Tensor
    ) -> List[Dict]:
        """
        Filtra le triple basandosi sulle entità rilevanti trovate da HGT
        """
        relevant_entity_names = {e["entity"].lower() for e in relevant_entities}
        relevant_triples = []
        
        for triple in triples:
            head = triple.get("head", "").lower()
            tail = triple.get("tail", "").lower()
            
            # Calcola relevance score
            relevance_score = 0.0
            
            # Bonus se coinvolge entità rilevanti
            if head in relevant_entity_names:
                relevance_score += 0.5
            if tail in relevant_entity_names:
                relevance_score += 0.5
            
            # Bonus aggiuntivo se entrambe sono rilevanti (path multi-hop!)
            if head in relevant_entity_names and tail in relevant_entity_names:
                relevance_score += 0.3
            
            # Aggiungi score dalla relazione
            relation = triple.get("relation", "")
            if any(keyword in relation for keyword in ["spouse", "born", "president", "capital", "founded"]):
                relevance_score += 0.2
            
            if relevance_score > 0:
                triple_with_score = triple.copy()
                triple_with_score["hgt_relevance_score"] = relevance_score
                relevant_triples.append(triple_with_score)
        
        # Ordina per relevance score
        relevant_triples.sort(key=lambda x: x["hgt_relevance_score"], reverse=True)
        
        return relevant_triples[:20]  # Top 20 triple
    
    def _extract_reasoning_patterns(
        self,
        embeddings: Dict[str, torch.Tensor],
        relevant_entities: List[Dict]
    ) -> List[Dict]:
        """
        Estrae pattern di reasoning analizzando cluster negli embedding space
        """
        patterns = []
        
        # Prendi embeddings delle entità rilevanti
        relevant_embeddings = []
        for entity in relevant_entities[:10]:
            relevant_embeddings.append(entity["embedding"])
        
        if len(relevant_embeddings) < 2:
            return patterns
        
        relevant_embeddings = torch.tensor(relevant_embeddings, device=self.device)
        
        # Trova cluster (pattern di reasoning)
        clusters = self._simple_clustering(relevant_embeddings, n_clusters=3)
        
        for i, cluster in enumerate(clusters):
            pattern = {
                "pattern_id": i,
                "entities_in_pattern": cluster["members"],
                "coherence": cluster["coherence"],
                "pattern_type": self._infer_pattern_type(cluster, relevant_entities)
            }
            patterns.append(pattern)
        
        return patterns
    
    def _identify_multihop_paths(
        self,
        relevant_entities: List[Dict],
        relevant_triples: List[Dict],
        embeddings: Dict[str, torch.Tensor]
    ) -> List[Dict]:
        """
        Identifica percorsi multi-hop basati su embeddings similarity
        """
        paths = []
        
        # Costruisci grafo dalle triple rilevanti
        graph = {}
        for triple in relevant_triples:
            head = triple["head"]
            tail = triple["tail"]
            relation = triple["relation"]
            
            if head not in graph:
                graph[head] = []
            graph[head].append((tail, relation))
        
        # Trova percorsi tra entità molto rilevanti
        high_score_entities = [e["entity"] for e in relevant_entities if e["score"] > 0.5]
        
        for start in high_score_entities[:3]:
            for end in high_score_entities[:3]:
                if start != end:
                    # BFS per trovare percorso
                    path = self._bfs_path(graph, start, end, max_depth=3)
                    if path:
                        paths.append({
                            "start": start,
                            "end": end,
                            "path": path,
                            "confidence": self._calculate_path_confidence(path, embeddings)
                        })
        
        # Ordina per confidence
        paths.sort(key=lambda x: x["confidence"], reverse=True)
        
        return paths[:5]  # Top 5 percorsi
    
    def _simple_clustering(
        self,
        embeddings: torch.Tensor,
        n_clusters: int = 3
    ) -> List[Dict]:
        """
        Clustering semplice K-means style
        """
        if len(embeddings) < n_clusters:
            return [{
                "members": list(range(len(embeddings))),
                "coherence": 1.0
            }]
        
        # Inizializza centri random
        centers = embeddings[torch.randperm(len(embeddings))[:n_clusters]]
        
        # K-means iterations
        for _ in range(10):
            # Assegna punti ai cluster
            distances = torch.cdist(embeddings, centers)
            assignments = distances.argmin(dim=1)
            
            # Aggiorna centri
            for i in range(n_clusters):
                mask = assignments == i
                if mask.any():
                    centers[i] = embeddings[mask].mean(dim=0)
        
        # Crea info cluster
        clusters = []
        for i in range(n_clusters):
            mask = assignments == i
            if mask.any():
                members = torch.where(mask)[0].cpu().tolist()
                
                # Calcola coherence (similarità media nel cluster)
                cluster_embs = embeddings[mask]
                if len(cluster_embs) > 1:
                    similarities = F.cosine_similarity(
                        cluster_embs.unsqueeze(1),
                        cluster_embs.unsqueeze(0),
                        dim=2
                    )
                    coherence = similarities.mean().item()
                else:
                    coherence = 1.0
                
                clusters.append({
                    "members": members,
                    "coherence": coherence
                })
        
        return clusters
    
    def _infer_pattern_type(self, cluster: Dict, entities: List[Dict]) -> str:
        """
        Inferisci il tipo di pattern dal cluster
        """
        # Guarda i tipi di entità nel cluster
        types = []
        for member_idx in cluster["members"]:
            if member_idx < len(entities):
                types.append(entities[member_idx]["type"])
        
        if len(set(types)) == 1:
            return f"homogeneous_{types[0]}"
        else:
            return "heterogeneous_mixed"
    
    def _bfs_path(
        self,
        graph: Dict,
        start: str,
        end: str,
        max_depth: int = 3
    ) -> Optional[List[Tuple[str, str]]]:
        """
        BFS per trovare percorso nel grafo
        """
        if start == end:
            return []
        
        from collections import deque
        
        queue = deque([(start, [])])
        visited = {start}
        
        while queue:
            node, path = queue.popleft()
            
            if len(path) >= max_depth:
                continue
            
            if node in graph:
                for next_node, relation in graph[node]:
                    if next_node == end:
                        return path + [(node, relation, next_node)]
                    
                    if next_node not in visited:
                        visited.add(next_node)
                        queue.append((next_node, path + [(node, relation, next_node)]))
        
        return None
    
    def _calculate_path_confidence(
        self,
        path: List[Tuple[str, str, str]],
        embeddings: Dict[str, torch.Tensor]
    ) -> float:
        """
        Calcola confidence del percorso basata su embedding similarity
        """
        if not path:
            return 0.0
        
        # Base confidence
        confidence = 1.0 / (1.0 + len(path))  # Penalizza percorsi lunghi
        
        # Bonus per relazioni importanti
        important_relations = ["spouse", "born_in", "president", "founded", "capital"]
        for _, relation, _ in path:
            if any(rel in relation for rel in important_relations):
                confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _calculate_confidence_scores(
        self,
        entities: List[Dict],
        triples: List[Dict],
        paths: List[Dict]
    ) -> Dict[str, float]:
        """
        Calcola punteggi di confidence complessivi
        """
        # Media dei top entity scores
        entity_confidence = np.mean([e["score"] for e in entities[:5]]) if entities else 0.0
        
        # Media dei top triple scores
        triple_confidence = np.mean([t["hgt_relevance_score"] for t in triples[:5]]) if triples else 0.0
        
        # Media dei path confidences
        path_confidence = np.mean([p["confidence"] for p in paths]) if paths else 0.0
        
        return {
            "entity_confidence": float(entity_confidence),
            "triple_confidence": float(triple_confidence),
            "path_confidence": float(path_confidence),
            "overall_confidence": float((entity_confidence + triple_confidence + path_confidence) / 3)
        }
