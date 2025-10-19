# train_projector.py
"""
Contrastive training for soft prompt projector.
Aligns graph embeddings with LLM embedding space.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Dict, Tuple
import json
from soft_prompting import SoftPromptProjector, load_graph_embeddings
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModel


class ContrastiveProjectorTrainer:
    """
    Train projector to align graph embeddings with LLM space using contrastive learning.
    """

    def __init__(
        self,
        d_graph: int,
        d_llm: int,
        device: str = "cuda",
        temperature: float = 0.07
    ):
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.projector = SoftPromptProjector(d_graph, d_llm).to(self.device)
        self.temperature = temperature

    def contrastive_loss(
        self,
        graph_embs: torch.Tensor,
        text_embs: torch.Tensor,
        labels: torch.Tensor
    ) -> torch.Tensor:
        """
        InfoNCE contrastive loss.

        Args:
            graph_embs: [B, d_graph] embeddings from graph
            text_embs: [B, d_llm] embeddings from text
            labels: [B] binary labels (1 = positive pair, 0 = negative)

        Returns:
            Scalar loss
        """
        # Project graph embeddings
        proj_embs = self.projector(graph_embs)  # [B, d_llm]

        # Normalize
        proj_embs = F.normalize(proj_embs, dim=-1)
        text_embs = F.normalize(text_embs, dim=-1)

        # Compute similarity matrix
        sim_matrix = torch.matmul(proj_embs, text_embs.T) / self.temperature  # [B, B]

        # For each graph emb, find its matching text emb
        # Positive pairs: labels == 1
        # Negative pairs: labels == 0

        # Simple InfoNCE: maximize similarity for positive pairs
        pos_mask = labels.unsqueeze(1) == labels.unsqueeze(0)  # [B, B]
        neg_mask = ~pos_mask

        # For each row, compute loss
        losses = []
        for i in range(sim_matrix.shape[0]):
            if labels[i] == 0:
                continue  # Skip negative samples as anchors

            pos_sim = sim_matrix[i][pos_mask[i]].mean()
            neg_sim = sim_matrix[i][neg_mask[i]]

            # InfoNCE: -log(exp(pos) / (exp(pos) + sum(exp(neg))))
            numerator = torch.exp(pos_sim)
            denominator = numerator + torch.exp(neg_sim).sum()
            loss = -torch.log(numerator / denominator)
            losses.append(loss)

        if losses:
            return torch.stack(losses).mean()
        else:
            return torch.tensor(0.0, device=self.device)

    def train_step(
        self,
        graph_embs: torch.Tensor,
        text_embs: torch.Tensor,
        labels: torch.Tensor,
        optimizer: torch.optim.Optimizer
    ) -> float:
        """Single training step."""
        optimizer.zero_grad()
        loss = self.contrastive_loss(graph_embs, text_embs, labels)
        loss.backward()
        optimizer.step()
        return loss.item()

    def train(
        self,
        train_data: List[Tuple[torch.Tensor, torch.Tensor, int]],
        epochs: int = 50,
        lr: float = 1e-3,
        batch_size: int = 32
    ):
        """
        Train the projector.

        Args:
            train_data: List of (graph_emb, text_emb, label) tuples
            epochs: Number of epochs
            lr: Learning rate
            batch_size: Batch size
        """
        optimizer = torch.optim.AdamW(self.projector.parameters(), lr=lr)

        for epoch in range(epochs):
            # Shuffle data
            import random
            random.shuffle(train_data)

            epoch_loss = 0.0
            num_batches = 0

            for i in range(0, len(train_data), batch_size):
                batch = train_data[i:i+batch_size]

                # Collate batch
                graph_embs = torch.stack([x[0] for x in batch]).to(self.device)
                text_embs = torch.stack([x[1] for x in batch]).to(self.device)
                labels = torch.tensor([x[2] for x in batch], device=self.device)

                loss = self.train_step(graph_embs, text_embs, labels, optimizer)
                epoch_loss += loss
                num_batches += 1

            avg_loss = epoch_loss / num_batches if num_batches > 0 else 0
            print(f"Epoch {epoch+1}/{epochs} | Loss: {avg_loss:.4f}")

    def save(self, path: str):
        """Save trained projector."""
        torch.save(self.projector.state_dict(), path)
        print(f"[INFO] Projector saved to {path}")

    def load(self, path: str):
        """Load trained projector."""
        self.projector.load_state_dict(torch.load(path, map_location=self.device))
        print(f"[INFO] Projector loaded from {path}")


def create_training_data_from_graph(
    entity_emb_path: str = "outputs/graph_entity_embs.pt",
    wd_emb_path: str = "outputs/graph_wikidata_embs.pt",
    triples_path: str = "outputs/triples_expanded.json",
    llm_name: str = "gpt2",
    device: str = "cuda",
    num_negatives: int = 5
) -> List[Tuple[torch.Tensor, torch.Tensor, int]]:
    """
    Create contrastive training data from graph.

    Positive pairs: (entity_emb, text_description_of_entity)
    Negative pairs: (entity_emb, text_description_of_random_other_entity)

    Args:
        entity_emb_path: Path to entity embeddings
        wd_emb_path: Path to wikidata embeddings
        triples_path: Path to triples
        llm_name: LLM model for text embeddings
        device: Device
        num_negatives: Number of negatives per positive

    Returns:
        List of (graph_emb, text_emb, label) tuples
    """
    dev = torch.device(device if torch.cuda.is_available() else "cpu")

    # Load graph embeddings
    z_ent, ent_names, z_wd, qids = load_graph_embeddings(
        entity_emb_path, wd_emb_path, triples_path, device=dev
    )

    # Load LLM for text embeddings
    tokenizer = AutoTokenizer.from_pretrained(llm_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Use last layer of LLM as text encoder
    llm = AutoModel.from_pretrained(llm_name).to(dev)

    def get_text_emb(text: str) -> torch.Tensor:
        """Get LLM embedding for text."""
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128).to(dev)
        with torch.no_grad():
            outputs = llm(**inputs)
            # Use mean of last hidden state
            emb = outputs.last_hidden_state.mean(dim=1).squeeze(0)
        return emb

    # Build training data
    training_data = []

    # Positive pairs: entity and its description
    for i, ent_name in enumerate(ent_names):
        graph_emb = z_ent[i]

        # Create text description
        text_desc = f"The entity {ent_name}"

        # Get text embedding
        text_emb = get_text_emb(text_desc)

        # Positive pair
        training_data.append((graph_emb.cpu(), text_emb.cpu(), 1))

        # Negative pairs: random other entities
        import random
        neg_indices = random.sample(range(len(ent_names)), min(num_negatives, len(ent_names)-1))
        for neg_idx in neg_indices:
            if neg_idx == i:
                continue
            neg_text = f"The entity {ent_names[neg_idx]}"
            neg_text_emb = get_text_emb(neg_text)
            training_data.append((graph_emb.cpu(), neg_text_emb.cpu(), 0))

    print(f"[INFO] Created {len(training_data)} training pairs")
    return training_data


def main():
    """Example training script."""
    print("Creating training data...")
    train_data = create_training_data_from_graph(
        device="cuda",
        num_negatives=3
    )

    # Get dimensions
    d_graph = train_data[0][0].shape[0]
    d_llm = train_data[0][1].shape[0]

    print(f"Graph dim: {d_graph}, LLM dim: {d_llm}")

    # Initialize trainer
    trainer = ContrastiveProjectorTrainer(
        d_graph=d_graph,
        d_llm=d_llm,
        device="cuda"
    )

    # Train
    print("Training projector...")
    trainer.train(train_data, epochs=20, lr=1e-3, batch_size=16)

    # Save
    trainer.save("outputs/trained_projector.pt")


if __name__ == "__main__":
    main()
