"""Attention-based GNN placement model for component position prediction.

Predicts (x, y, rotation) for each component given board outline and
bipartite component-net graph features. Uses multi-head attention for
component-net message passing with sigmoid outputs scaled to board dimensions.

Security (threat model):
  T-16-03: Model weights loaded with torch.load(weights_only=True).
  T-16-05: Training compute bounded by gradient clipping at 1.0.

Usage::

    from kicad_agent.placement.model import PlacementModel, BipartiteAttentionLayer

    model = PlacementModel()
    predictions = model(comp_features, net_features, adj_matrix, board_w, board_h)
    # predictions shape: (batch, n_components, 3) -- [x, y, rotation]
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class BipartiteAttentionLayer(nn.Module):
    """Multi-head attention layer for bipartite component-net message passing.

    Component nodes query against net node keys/values using nn.MultiheadAttention.
    An adjacency matrix masks attention so components only attend to connected nets.
    A residual connection adds the attention output to the input component features.

    Args:
        comp_dim: Dimension of component feature vectors.
        net_dim: Dimension of net feature vectors.
        n_heads: Number of attention heads.
    """

    def __init__(self, comp_dim: int, net_dim: int, n_heads: int = 4) -> None:
        super().__init__()
        self.comp_proj = nn.Linear(comp_dim, comp_dim)
        self.net_proj = nn.Linear(net_dim, comp_dim)
        self.attention = nn.MultiheadAttention(
            embed_dim=comp_dim,
            num_heads=n_heads,
            batch_first=True,
        )

    def forward(
        self,
        comp_features: torch.Tensor,
        net_features: torch.Tensor,
        adj_matrix: torch.Tensor,
    ) -> torch.Tensor:
        """Apply bipartite attention from components to nets.

        Args:
            comp_features: (batch, n_comp, comp_dim) component embeddings.
            net_features: (batch, n_net, net_dim) net embeddings.
            adj_matrix: (batch, n_comp, n_net) binary adjacency.

        Returns:
            (batch, n_comp, comp_dim) updated component features with residual.
        """
        # Project net features into component dimension space
        projected_nets = self.net_proj(net_features)  # (B, n_net, comp_dim)

        # Build attention mask: True = ignore position
        # adj_matrix is (B, n_comp, n_net) with 1=connected, 0=disconnected
        # MHA attn_mask: True positions are *ignored*
        attn_mask = (adj_matrix == 0)  # (B, n_comp, n_net) True = not connected

        # Handle disconnected components: if all positions are masked (no net
        # connections), allow attending to all nets to avoid NaN from softmax
        # over all -inf values.
        fully_masked = attn_mask.all(dim=-1, keepdim=True)  # (B, n_comp, 1)
        attn_mask = torch.where(fully_masked, False, attn_mask)

        # For MultiheadAttention with batch_first:
        # query: (B, n_comp, comp_dim)
        # key/value: (B, n_net, comp_dim)
        # attn_mask: (n_comp, n_net) or (B*n_heads, n_comp, n_net)
        B = comp_features.size(0)
        n_heads = self.attention.num_heads

        # Expand mask for multi-head: (B*n_heads, n_comp, n_net)
        if attn_mask.dtype != torch.bool:
            attn_mask = attn_mask.bool()
        expanded_mask = attn_mask.unsqueeze(1).expand(
            B, n_heads, -1, -1
        ).reshape(B * n_heads, attn_mask.size(1), attn_mask.size(2))

        # Query from component features
        query = self.comp_proj(comp_features)

        attn_out, _ = self.attention(
            query=query,
            key=projected_nets,
            value=projected_nets,
            attn_mask=expanded_mask,
        )

        # Residual connection
        return comp_features + attn_out


class PlacementModel(nn.Module):
    """Attention-based GNN for component placement prediction.

    Operates on the bipartite component-net graph from PlacementGraph.
    Three message-passing layers with LayerNorm and ReLU activations,
    followed by per-component (x, y, rotation) output heads.

    Output:
        - x: sigmoid scaled to [0, board_width]
        - y: sigmoid scaled to [0, board_height]
        - rotation: sigmoid mapped to [-180, 180] degrees

    Args:
        comp_feature_dim: Input component feature dimension (default 32).
        net_feature_dim: Input net feature dimension (default 16).
        hidden_dim: Hidden dimension for message passing (default 128).
        n_layers: Number of attention layers (default 3).
        n_heads: Number of attention heads per layer (default 4).
    """

    def __init__(
        self,
        comp_feature_dim: int = 32,
        net_feature_dim: int = 16,
        hidden_dim: int = 128,
        n_layers: int = 3,
        n_heads: int = 4,
    ) -> None:
        super().__init__()
        self.comp_embed = nn.Linear(comp_feature_dim, hidden_dim)
        self.net_embed = nn.Linear(net_feature_dim, hidden_dim)

        self.attn_layers = nn.ModuleList([
            BipartiteAttentionLayer(hidden_dim, hidden_dim, n_heads)
            for _ in range(n_layers)
        ])
        self.layer_norms = nn.ModuleList([
            nn.LayerNorm(hidden_dim)
            for _ in range(n_layers)
        ])

        # Per-component output heads
        self.x_head = nn.Linear(hidden_dim, 1)
        self.y_head = nn.Linear(hidden_dim, 1)
        self.rot_head = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        comp_features: torch.Tensor,
        net_features: torch.Tensor,
        adj_matrix: torch.Tensor,
        board_w: torch.Tensor,
        board_h: torch.Tensor,
    ) -> torch.Tensor:
        """Predict (x, y, rotation) for each component.

        Args:
            comp_features: (batch, n_comp, comp_feature_dim) component features.
            net_features: (batch, n_net, net_feature_dim) net features.
            adj_matrix: (batch, n_comp, n_net) binary adjacency.
            board_w: (batch,) board width in mm.
            board_h: (batch,) board height in mm.

        Returns:
            (batch, n_comp, 3) predictions with columns [x, y, rotation].
        """
        # Embed into hidden dimension
        h_comp = F.relu(self.comp_embed(comp_features))  # (B, n_comp, hidden)
        h_net = F.relu(self.net_embed(net_features))      # (B, n_net, hidden)

        # Message passing layers with LayerNorm + ReLU
        for attn_layer, ln in zip(self.attn_layers, self.layer_norms):
            h_comp = attn_layer(h_comp, h_net, adj_matrix)
            h_comp = F.relu(ln(h_comp))

        # Per-component predictions
        x = torch.sigmoid(self.x_head(h_comp)).squeeze(-1) * board_w.unsqueeze(-1)
        y = torch.sigmoid(self.y_head(h_comp)).squeeze(-1) * board_h.unsqueeze(-1)
        rot = (torch.sigmoid(self.rot_head(h_comp)).squeeze(-1) * 360.0) - 180.0

        return torch.stack([x, y, rot], dim=-1)  # (B, n_comp, 3)
