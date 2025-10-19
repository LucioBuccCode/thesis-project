# hgt_train_utils.py
from typing import Dict, List, Tuple
import torch, torch.nn as nn, torch.nn.functional as F
from torch_geometric.nn import HGTConv
from torch_geometric.data import HeteroData

# ===== MODEL =====
class HGTEncoder(nn.Module):
    def __init__(self, metadata, in_dim: int, hidden: int = 384, heads: int = 2, layers: int = 2, drop: float = 0.3):
        """
        Enhanced HGT Encoder with Layer Normalization and increased dropout.

        Args:
            metadata: Graph metadata
            in_dim: Input dimension
            hidden: Hidden dimension
            heads: Number of attention heads
            layers: Number of HGT layers
            drop: Dropout rate (increased default to 0.3 for regularization)
        """
        super().__init__()
        self.proj = nn.Linear(in_dim, hidden, bias=False)

        # Add layer normalization for each node type
        self.input_norm = nn.ModuleDict()

        self.layers = nn.ModuleList([
            HGTConv(in_channels=hidden, out_channels=hidden, metadata=metadata, heads=heads)
            for _ in range(layers)
        ])

        # Layer normalization after each HGT layer
        self.layer_norms = nn.ModuleList([
            nn.ModuleDict({ntype: nn.LayerNorm(hidden) for ntype in metadata[0]})
            for _ in range(layers)
        ])

        self.drop = nn.Dropout(drop)
        self.metadata = metadata

    def forward(self, x_dict, edge_index_dict):
        # Project input
        x = {k: self.proj(v) for k, v in x_dict.items()}

        # Apply HGT layers with residual connections and layer norm
        for i, conv in enumerate(self.layers):
            x_prev = {k: v.clone() for k, v in x.items()}

            # HGT convolution
            x = conv(x, edge_index_dict)

            # Apply layer norm, dropout, activation
            for ntype in x.keys():
                x[ntype] = self.layer_norms[i][ntype](x[ntype])
                x[ntype] = F.relu(x[ntype])
                x[ntype] = self.drop(x[ntype])

                # Residual connection (if same size)
                if ntype in x_prev and x[ntype].shape == x_prev[ntype].shape:
                    x[ntype] = x[ntype] + x_prev[ntype]

        return x

class RelScorer(nn.Module):
    """Bilinear scorer per relazione: score = h^T W_r t."""
    def __init__(self, num_rels: int, dim: int):
        super().__init__()
        self.W = nn.Parameter(torch.randn(num_rels, dim, dim) * 0.02)
    def forward(self, h, r_ids, t):
        Wr = self.W[r_ids]                     # [B, d, d]
        hw = torch.bmm(h.unsqueeze(1), Wr).squeeze(1)
        return torch.sum(hw * t, dim=-1)       # [B]

# ===== EDGE COLLECTION (ALL TYPES) =====
def collect_training_edges(data: HeteroData) -> List[Tuple[str, torch.Tensor]]:
    triples = []
    for et in data.edge_types:
        ei = data[et].edge_index
        if ei is None or ei.numel() == 0:
            continue
        src, rel, dst = et
        key = f"{src}__{rel}__{dst}"
        triples.append((key, ei))
    return triples

def build_rel2id(pos_edges: List[Tuple[str, torch.Tensor]]) -> Dict[str, int]:
    rel_names = sorted(set([r for r,_ in pos_edges]))
    return {r:i for i,r in enumerate(rel_names)}

# ===== SAMPLER STABILE =====
def sample_batch(
    pos_edges: List[Tuple[str, torch.Tensor]],
    rel2id: Dict[str, int],
    per_rel: int = None,        # None=usa tutti; int=sotto-campiona per relazione
    num_neg: int = 2,
    filter_negs: bool = True,
    device: str = "cpu"
):
    pos_list = []
    true_tails = {}
    max_ent = 0

    for r_key, ei in pos_edges:
        if ei.numel() == 0: continue
        if per_rel is not None:
            idx = torch.randperm(ei.shape[1])[:min(per_rel, ei.shape[1])]
            e = ei[:, idx]
        else:
            e = ei
        rid = rel2id[r_key]
        max_ent = max(max_ent, int(e.max().item())+1)
        for hh, tt in e.t().tolist():
            pos_list.append((hh, rid, tt))
            if filter_negs:
                true_tails.setdefault((hh, rid), set()).add(tt)

    if not pos_list or max_ent == 0:
        return None

    # negativi tail-corruption, filtrati
    import random
    neg_list = []
    for (hh, rr, _) in pos_list:
        for _ in range(num_neg):
            if filter_negs:
                tries = 0
                while True:
                    tt_neg = random.randrange(max_ent)
                    if tt_neg not in true_tails.get((hh, rr), set()):
                        neg_list.append((hh, rr, tt_neg)); break
                    tries += 1
                    if tries > 10:
                        neg_list.append((hh, rr, tt_neg)); break
            else:
                tt_neg = random.randrange(max_ent)
                neg_list.append((hh, rr, tt_neg))

    heads = torch.tensor([p[0] for p in pos_list] + [n[0] for n in neg_list], dtype=torch.long, device=device)
    rels  = torch.tensor([p[1] for p in pos_list] + [n[1] for n in neg_list], dtype=torch.long, device=device)
    tails = torch.tensor([p[2] for p in pos_list] + [n[2] for n in neg_list], dtype=torch.long, device=device)
    labels = torch.cat([torch.ones(len(pos_list), device=device), torch.zeros(len(neg_list), device=device)], dim=0)
    return heads, rels, tails, labels

# ===== TRAIN LOOP (ALL EDGE TYPES) =====
def train_hgt_all_edges(
    data: HeteroData,
    device: str = "cuda",
    hidden: int = 384,
    layers: int = 2,
    lr: float = 3e-4,
    epochs: int = 80,
    neg_per_pos: int = 2,
    per_rel: int = 128,
    early: int = 8,
    clip: float = 1.0
):
    dev = torch.device("cuda" if (device=="cuda" and torch.cuda.is_available()) else "cpu")
    metadata = data.metadata()
    in_dim = int(next(iter(data.x_dict.values())).shape[-1])

    enc = HGTEncoder(metadata, in_dim=in_dim, hidden=hidden, heads=2, layers=layers).to(dev)
    # prepara dizionari su device
    x_dict = {k: v.detach().clone().to(dev).float() for k, v in data.x_dict.items()}
    edge_index_dict = {et: data[et].edge_index.to(dev) for et in data.edge_types}

    # edge set eterogeneo
    pos_edges = collect_training_edges(data)
    rel2id = build_rel2id(pos_edges)
    scorer = RelScorer(num_rels=len(rel2id), dim=hidden).to(dev)

    # Optimizer with stronger weight decay
    opt = torch.optim.AdamW(list(enc.parameters())+list(scorer.parameters()), lr=lr, weight_decay=5e-4)

    # Learning rate scheduler
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, mode='min', factor=0.5, patience=5, verbose=True
    )

    best, wait = float("inf"), 0
    history = {"train_loss": [], "train_acc": []}

    for ep in range(1, epochs+1):
        enc.train(); scorer.train()
        batch = sample_batch(pos_edges, rel2id=rel2id, per_rel=per_rel, num_neg=neg_per_pos, filter_negs=True, device=str(dev))
        if batch is None:
            raise RuntimeError("sample_batch returned None (no edges?)")
        heads, rel_ids, tails, labels = batch
        out_x = enc(x_dict, edge_index_dict)

        # Semplificazione: banca unica a seconda del tipo predominante nel batch
        z_ent = out_x.get('entity', None)
        z_wd  = out_x.get('wikidata', None)
        bank = z_ent if (z_ent is not None and heads.max().item() < z_ent.size(0)) else z_wd
        if bank is None:
            raise RuntimeError("No embedding bank available; check mapping logic.")
        h = bank[heads]; t = bank[tails]

        score = scorer(h, rel_ids, t)

        # Main loss
        loss = F.binary_cross_entropy_with_logits(score, labels)

        # Add L2 regularization on embeddings (helps prevent overfitting on small graphs)
        reg_loss = 0.01 * (h.pow(2).mean() + t.pow(2).mean())
        total_loss = loss + reg_loss

        opt.zero_grad(set_to_none=True)
        total_loss.backward()
        if clip > 0:
            nn.utils.clip_grad_norm_(list(enc.parameters())+list(scorer.parameters()), clip)
        opt.step()

        with torch.no_grad():
            acc = ((torch.sigmoid(score)>0.5).float() == labels).float().mean().item()

        history["train_loss"].append(loss.item())
        history["train_acc"].append(acc)

        print(f"Epoch {ep:03d} | loss {loss.item():.4f} | reg {reg_loss.item():.4f} | acc {acc:.3f} | lr {opt.param_groups[0]['lr']:.2e}")

        # Learning rate scheduling
        scheduler.step(loss)

        # Early stopping with tolerance
        if loss.item() < best - 1e-4:
            best, wait = loss.item(), 0
        else:
            wait += 1
            if early > 0 and wait >= early:
                print(f"Early stop @ epoch {ep} (patience={early})")
                break

    enc.eval()
    with torch.no_grad():
        out_x = enc(x_dict, edge_index_dict)
    return {k: v.detach().cpu() for k, v in out_x.items()}
