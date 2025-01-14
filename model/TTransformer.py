import ipdb
import math
from typing import Tuple

import torch
import torch.nn.functional as F

from torch import nn, Tensor
from torch.utils.data import dataset
from torch.nn import TransformerEncoder, TransformerEncoderLayer


class PositionalEncoding(nn.Module):

	def __init__(self, d_model, dropout=0.1, max_len=5000):
		super(PositionalEncoding, self).__init__()
		self.dropout = nn.Dropout(p=dropout)

		pe = torch.zeros(max_len, d_model)
		position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
		div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
		pe[:, 0::2] = torch.sin(position * div_term)
		pe[:, 1::2] = torch.cos(position * div_term)
		pe = pe.unsqueeze(0).transpose(0, 1)
		self.register_buffer('pe', pe)

	def forward(self, x):
		x = x + self.pe[:x.size(0), :]
		return self.dropout(x)



#class TTransformerModel(nn.Module):
#
#    def __init__(self, ntoken: int, d_model: int, nhead: int, d_hid: int,
#                 nlayers: int, dropout: float = 0.5):
#        super().__init__()
#        self.model_type = "Transformer"
#        self.pos_encoder = PositionalEncoding(d_model, dropout)
#        encoder_layers = TransformerEncoderLayer(d_model, nhead, d_hid, dropout)
#        self.transformer_encoder = TransformerEncoder(encoder_layers, nlayers)
#        self.encoder = nn.Embedding(ntoken, d_model)
#        self.d_model = d_model
#        self.decoder = nn.Linear(d_model, ntoken)
#
#        self.init_weights()
#
#    def init_weights(self) -> None:
#        initrange = 0.1
#        self.encoder.weight.data.uniform_(-initrange, initrange)
#        self.decoder.bias.data.zero_()
#        self.decoder.weight.data.uniform_(-initrange, initrange)
#
#    def forward(self, src: Tensor, src_mask: Tensor) -> Tensor:
#        """
#        Args:
#            src: Tensor, shape [seq_len, batch_size]
#            src_mask: Tensor, shape [seq_len, seq_len]
#        Returns:
#            output Tensor of shape [seq_len, batch_size, ntoken]
#        """
#        src = self.encoder(src) * math.sqrt(self.d_model)
#        src = self.pos_encoder(src)
#        output = self.transformer_encoder(src, src_mask)
#        output = self.decoder(output)
#        return output

class TTransformerModel(nn.Module):

	def __init__(self, ntoken: int, d_model: int = 768, nhead: int = 8, d_hid: int = 768, nlayers: int = 2, dropout: float = 0.5):
		super().__init__()
		self.model_type = "Transformer"
		#self.pos_encoder = PositionalEncoding(d_model, dropout)
		encoder_layers = TransformerEncoderLayer(d_model, nhead, d_hid, dropout, batch_first=True)
		self.transformer_encoder = TransformerEncoder(encoder_layers, nlayers)
		self.encoder = nn.Embedding(ntoken, d_model)
		self.d_model = d_model
		#self.decoder = nn.Linear(d_model, ntoken)

		#self.init_weights()

	def init_weights(self) -> None:
		initrange = 0.1
		self.encoder.weight.data.uniform_(-initrange, initrange)
		#self.decoder.bias.data.zero_()
		#self.decoder.weight.data.uniform_(-initrange, initrange)

	def forward(self, data, src: Tensor, src_mask: Tensor) -> Tensor:
		"""
		Args:
			src     : Tensor, shape [batch_size, seq_len, embedding dimension]
			src_mask: Tensor, shape [batch_size, seq_len]
		Returns:
			output Tensor of shape [batch_size, seq_len]
		"""
		batch_size = src.shape[0]
		#src = self.encoder(src) * math.sqrt(self.d_model)
		#src = self.pos_encoder(src)
		cls_tid = data.input_ids[0][0]
		cls_emb = self.encoder(cls_tid) * math.sqrt(self.d_model)
		cls_emb = cls_emb.unsqueeze(0).unsqueeze(0).repeat(batch_size, 1, 1)
		cls_msk = torch.ones(batch_size, 1).to(cls_emb.device)

		src = torch.cat((cls_emb, src), dim=1)
		src_mask = torch.cat((cls_msk, src_mask), dim=1)

		## Forward through encoder
		output = self.transformer_encoder(src, src_key_padding_mask=src_mask)

		return output


def generate_square_subsequent_mask(sz: int) -> Tensor:
	"""Generates an upper-triangular matrix of -inf, with zeros on diag."""
	return torch.triu(torch.ones(sz, sz) * float('-inf'), diagonal=1)
