import copy
import ipdb
import sys,os
import pickle
import random
import argparse
import numpy as np
import pandas as pd
import sklearn.metrics as metrics

from tqdm import tqdm
from sklearn.model_selection import KFold

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset
from torch_geometric.data import Data
#from torch_geometric.data import DataLoader
from torch_geometric.loader import DataLoader
from torch_geometric.nn import global_mean_pool, global_max_pool
from torch_geometric.nn import GCNConv,GraphConv,GINConv,GATConv
from torch_scatter import scatter_mean, scatter_max, scatter_add

from utils import *
from utils import EarlyStopping
from model.duck import CCCTNet
from model.duck import ComboNet
from model.gat import SimpleGATNet
from model.gcn import SimpleGCNNet, TripleGCNNet
from model.bert_gat import SimpleGATBERTNet, TripleGATBERTNet
from dataset import CommentTreeDataset, UserTreeDataset, DuckDataset

# Seed
seed = 123
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
torch.cuda.manual_seed_all(seed)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True

logger = get_logger('train')

class DUCK:
	def __init__(self,args):
		self.parse_args(args)

	def parse_args(self, args):
		self.args = args
		self.modelName = args.modelName
		self.mode = args.mode
		self.base_dir = args.baseDirectory
		self.datasetName = args.datasetName
		self.foldnum = args.foldnum
		self.seed = args.seed
		self.lr = args.learningRate
		self.glr = args.learningRateGraph
		self.weight_decay = args.weight_decay
		self.patience = args.patience
		self.n_epochs = args.n_epochs
		self.batchsize = args.batchsize
		self.multi_gpu = args.multi_gpu


	def loadfolddatawithKnownFold(self):
		print("\nLoading 5-fold data of fold [{}]...".format(self.foldnum))
		fold_str = str(self.foldnum)
		cc_path = "{}/{}_5fold/fold{}".format(self.base_dir, self.datasetName, fold_str)
		train_file_path = os.path.join(cc_path, "_x_train.pkl")
		test_file_path = os.path.join(cc_path, "_x_test.pkl")
		with open(train_file_path, "rb") as f:
			trainlist = pickle.load(f)
		with open(test_file_path, "rb") as ftest:
			testlist = pickle.load(ftest)
		return trainlist, testlist

	def loadfolddata(self):
		df = pd.read_pickle(self.base_dir+'data.pkl')
		kf = KFold(n_splits=5, shuffle=True, random_state=self.seed)
		result = next(kf.split(df),None)
		train = df.iloc[result[0]]
		test = df.iloc[result[1]]
		return train, test

	def init_model(self):
		print("\nBuilding model {}...".format(self.modelName))
		MODEL_CLASS = {
			#"Simple_GCN": SimpleGCNNet(),
			#"Triple_GCN": TripleGCNNet(),
			#"Simple_GAT": SimpleGATNet(),
			"Simple_GAT_BERT": SimpleGATBERTNet(
				D_in=768, 
				hid_feats=768, 
				out_feats=768, 
				H=32, 
				D_out=self.args.n_classes, 
				gat_dropout=self.args.dropout_gat
			),
			"CCCTNet": CCCTNet(in_feats=768, hid_feats=768, out_feats=768, D_in=768, D_H=64, D_out=self.args.n_classes), 
			#"Triple_GAT_BERT": TripleGATBERTNet(),
			#"DUCK": ComboNet(),
		}
		model = MODEL_CLASS[self.modelName]
		return model

	def loadData(self):
		print("Loading dataset for training...")
		MODE_CLASS = {
			"CommentTree": CommentTreeDataset,
			"UserTree": UserTreeDataset,
			"DUCK": DuckDataset
		}
		print("- Loading train set, ", end="")
		traindata_list = MODE_CLASS[self.mode](self.args, self.x_train, self.base_dir)
		print("length of training list", len(traindata_list))
		print("- Loading test  set, ", end="")
		testdata_list  = MODE_CLASS[self.mode](self.args, self.x_test , self.base_dir)
		print("length of testing  list" , len(testdata_list))
		return traindata_list, testdata_list

	def train(self, load=False):
		if load:
			model = self.load_model(self.config.pretrained_model_path)
		device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
		test_accs = []
		NR_F1 = []
		FR_F1 = []
		TR_F1 = []
		UR_F1 = []

		x_train, x_test = self.loadfolddatawithKnownFold()
		self.x_train, self.x_test = x_train, x_test
		#model = TripleGCNNet(16,256,64,pooling='scatter_mean').to(device)
		#print(model)
		#should based on the modelName to init the model dynamically
		model = self.init_model()
		model.to(device)
		
		GNN_params =  list(map(id, model.gnn.conv1.parameters()))
		GNN_params += list(map(id, model.gnn.conv2.parameters()))
		
		if "Triple" in self.modelName:
			GNN_params += list(map(id, model.gnn.conv3.parameters()))
		base_params=filter(lambda p:id(p) not in GNN_params,model.parameters())
		optimizer = torch.optim.Adam([
			{"params": base_params},
			{"params": model.gnn.conv1.parameters(), "lr": self.glr},
			{"params": model.gnn.conv2.parameters(), "lr": self.glr}
		], lr=self.lr, weight_decay=self.weight_decay)

		if "Triple" in self.modelName:
			optimizer = torch.optim.Adam([
				{"params": base_params},
				{"params": model.gnn.conv1.parameters(), "lr": self.glr},
				{"params": model.gnn.conv2.parameters(), "lr": self.glr},
				{"params": model.gnn.conv3.parameters(), "lr": self.glr},
			], lr=self.lr, weight_decay=self.weight_decay)

		## Load dataset for training
		traindata_list, testdata_list = self.loadData()
		train_loader = DataLoader(traindata_list, batch_size=self.batchsize, shuffle=True, num_workers=0)#5)
		test_loader  = DataLoader(testdata_list , batch_size=self.batchsize, shuffle=True, num_workers=0)#5)
		
		train_losses = []
		val_losses = []
		train_accs = []
		val_accs = []
		early_stopping = EarlyStopping(args=self.args, patience=self.patience, verbose=True)

		## Open file for saving metrics
		best_metrics = None
		result_file = "{}/{}.txt".format(self.args.result_path, self.args.datasetName)
		if os.path.isfile(result_file):
			fw = open(result_file, "a")
		else:
			fw = open(result_file, "w")
			fw.write("{:4s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\t{:6s}\n".format(
				"Fold", "lr", "glr", "dropout", 
				"Acc.", "macroF", 
				"Acc1", "Prec1", "Recll1", "F1",
				"Acc2", "Prec2", "Recll2", "F2",
				"Acc3", "Prec3", "Recll3", "F3",
				"Acc4", "Prec4", "Recll4", "F4"
			))

		print("\nStart training...")
		for epoch in range(self.args.n_epochs):

			## Training
			model.train()
			avg_loss = []
			avg_acc = []
			batch_idx = 0
			tqdm_train_loader = tqdm(train_loader, desc="Epoch: {}, Train".format(epoch))
			for Batch_data in tqdm_train_loader:
				#ipdb.set_trace()
				Batch_data.to(device)
				dataList = Batch_data.to_data_list()
				#emb, out_labels = model(Batch_data)
				out_labels = model(Batch_data)
				finalloss = F.nll_loss(out_labels,Batch_data.y)
				
				optimizer.zero_grad()
				loss = finalloss
				loss.backward()
				avg_loss.append(loss.item())
				optimizer.step()

				_, pred = out_labels.max(dim=-1)
				correct = pred.eq(Batch_data.y).sum().item()
				train_acc = correct / len(Batch_data.y)
				avg_acc.append(train_acc)

				#print("Epoch {:05d} | Batch{:02d} | Train_Loss {:.4f}| Train_Accuracy {:.4f}".format(epoch, batch_idx, loss.item(), train_acc))
				#logger.info("Epoch {:05d} | Batch{:02d} | Train_Loss {:.4f}| Train_Accuracy {:.4f}".format(epoch, batch_idx, loss.item(), train_acc))

				batch_idx = batch_idx + 1

			train_losses.append(np.mean(avg_loss))
			train_accs.append(np.mean(avg_acc))

			## Evaluation
			model.eval()
			pred_all, y_all = [], []
			temp_val_losses = []
			temp_val_accs = []
			temp_val_Acc_all, \
			temp_val_Acc1, temp_val_Prec1, temp_val_Recll1, temp_val_F1, \
			temp_val_Acc2, temp_val_Prec2, temp_val_Recll2, temp_val_F2, \
			temp_val_Acc3, temp_val_Prec3, temp_val_Recll3, temp_val_F3, \
			temp_val_Acc4, temp_val_Prec4, temp_val_Recll4, temp_val_F4 = [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []
			tqdm_test_loader = tqdm(test_loader, desc="Epoch: {}, Eval".format(epoch))
			with torch.no_grad():
				for Batch_data in tqdm_test_loader:
					optimizer.zero_grad()
					Batch_data.to(device)
					#val_emb, val_out = model(Batch_data)
					val_out = model(Batch_data)
					val_loss = F.nll_loss(val_out, Batch_data.y)
					temp_val_losses.append(val_loss.item())
					
					_, val_pred = val_out.max(dim=1)
					correct = val_pred.eq(Batch_data.y).sum().item()
					val_acc = correct / len(Batch_data.y)

					#Acc_all, \
					#Acc1, Prec1, Recll1, F1, \
					#Acc2, Prec2, Recll2, F2, \
					#Acc3, Prec3, Recll3, F3, \
					#Acc4, Prec4, Recll4, F4 = evaluationRumour4(val_pred, Batch_data.y)
					#
					#temp_val_Acc_all.append(Acc_all)
					#temp_val_Acc1.append(Acc1), temp_val_Prec1.append(Prec1), temp_val_Recll1.append(Recll1), temp_val_F1.append(F1), \
					#temp_val_Acc2.append(Acc2), temp_val_Prec2.append(Prec2), temp_val_Recll2.append(Recll2), temp_val_F2.append(F2), \
					#temp_val_Acc3.append(Acc3), temp_val_Prec3.append(Prec3), temp_val_Recll3.append(Recll3), temp_val_F3.append(F3), \
					#temp_val_Acc4.append(Acc4), temp_val_Prec4.append(Prec4), temp_val_Recll4.append(Recll4), temp_val_F4.append(F4)
					#temp_val_accs.append(val_acc)

					## Save predictions & labels
					pred_all.append(val_pred)
					y_all.append(Batch_data.y)

			## Evaluate all predictions
			pred_all, y_all = torch.cat(pred_all), torch.cat(y_all)
			
			Acc_all, \
			Acc1, Prec1, Recll1, F1, \
			Acc2, Prec2, Recll2, F2, \
			Acc3, Prec3, Recll3, F3, \
			Acc4, Prec4, Recll4, F4 = evaluationRumour4(pred_all, y_all)
			#ipdb.set_trace()

			val_losses.append(np.mean(temp_val_losses))
			#val_accs.append(np.mean(temp_val_accs))
			#print("Epoch {:05d} | Val_Loss {:.4f} | Val_Accuracy {:.4f}".format(epoch, np.mean(temp_val_losses),np.mean(temp_val_accs)))
			print("Epoch {:05d} | Val_Loss {:.4f}".format(epoch, np.mean(temp_val_losses)))
			temp_mean_val_losses = np.mean(temp_val_losses)
			#temp_mean_val_accs = np.mean(temp_val_accs)
			#logger.info(f"epoch {epoch}, {temp_mean_val_losses},{temp_mean_val_accs}")

			#res = ["acc:{:.4f},macroF:{:.4f}".format(np.mean(temp_val_Acc_all), (np.mean(temp_val_F1) + np.mean(temp_val_F2) + np.mean(temp_val_F3) + np.mean(temp_val_F4)) / self.args.n_classes), 
			#	   "C1:{:.4f},{:.4f},{:.4f},{:.4f}".format(np.mean(temp_val_Acc1), np.mean(temp_val_Prec1), np.mean(temp_val_Recll1), np.mean(temp_val_F1)),
			#	   "C2:{:.4f},{:.4f},{:.4f},{:.4f}".format(np.mean(temp_val_Acc2), np.mean(temp_val_Prec2), np.mean(temp_val_Recll2), np.mean(temp_val_F2)),
			#	   "C3:{:.4f},{:.4f},{:.4f},{:.4f}".format(np.mean(temp_val_Acc3), np.mean(temp_val_Prec3), np.mean(temp_val_Recll3), np.mean(temp_val_F3)),
			#	   "C4:{:.4f},{:.4f},{:.4f},{:.4f}".format(np.mean(temp_val_Acc4), np.mean(temp_val_Prec4), np.mean(temp_val_Recll4), np.mean(temp_val_F4))]
			#print('results:', res)
			#logger.info(f"results: {res}")

			#is_best = early_stopping(
			#	np.mean(temp_val_losses), np.mean(temp_val_accs), np.mean(temp_val_F1), np.mean(temp_val_F2),
			#	np.mean(temp_val_F3), np.mean(temp_val_F4), model, self.args.modelName, "{}{}".format(self.args.datasetName, self.args.foldnum)
			#)
			
			#accs = np.mean(temp_val_accs)
			#F1 = np.mean(temp_val_F1)
			#F2 = np.mean(temp_val_F2)
			#F3 = np.mean(temp_val_F3)
			#F4 = np.mean(temp_val_F4)

			res = ["acc: {:.4f}, macroF: {:.4f}".format(Acc_all, (F1 + F2 + F3 + F4) / self.args.n_classes), 
				   "C1 : {:.4f}, {:.4f}, {:.4f}, {:.4f}".format(Acc1, Prec1, Recll1, F1),
				   "C2 : {:.4f}, {:.4f}, {:.4f}, {:.4f}".format(Acc2, Prec2, Recll2, F2),
				   "C3 : {:.4f}, {:.4f}, {:.4f}, {:.4f}".format(Acc3, Prec3, Recll3, F3),
				   "C4 : {:.4f}, {:.4f}, {:.4f}, {:.4f}".format(Acc4, Prec4, Recll4, F4)]
			for res_ in res:
				print(res_)
			logger.info(f"results: {res}")

			is_best = early_stopping(
				temp_mean_val_losses, Acc_all, F1, F2, F3, F4, 
				model, self.args.modelName, "{}{}".format(self.datasetName, self.foldnum)
			)
			accs = Acc_all

			if early_stopping.early_stop:
				print("Early stopping")
				logger.info(f"Early stopping")
				accs = early_stopping.accs
				F1 = early_stopping.F1
				F2 = early_stopping.F2
				F3 = early_stopping.F3
				F4 = early_stopping.F4
				break
			torch.cuda.empty_cache()

			logger.info(f"acc {accs}, F1 {F1} | F2 {F2} | F3 {F3} | F4 {F4} ")

			## TODO: add recording best scores!
			if is_best:
				#best_metrics = {
				#	"Acc.": accs, "macroF": (F1 + F2 + F3 + F4) / self.args.n_classes, 
				#	"Acc1": np.mean(temp_val_Acc1), "Prec1": np.mean(temp_val_Prec1), "Recll1": np.mean(temp_val_Recll1), "F1": F1, 
				#	"Acc2": np.mean(temp_val_Acc2), "Prec2": np.mean(temp_val_Prec2), "Recll2": np.mean(temp_val_Recll2), "F2": F2, 
				#	"Acc3": np.mean(temp_val_Acc3), "Prec3": np.mean(temp_val_Prec3), "Recll3": np.mean(temp_val_Recll3), "F3": F3, 
				#	"Acc4": np.mean(temp_val_Acc4), "Prec4": np.mean(temp_val_Prec4), "Recll4": np.mean(temp_val_Recll4), "F4": F4, 
				#}
				best_metrics = {
					"Acc.": accs, "macroF": (F1 + F2 + F3 + F4) / self.args.n_classes, 
					"Acc1": Acc1, "Prec1": Prec1, "Recll1": Recll1, "F1": F1, 
					"Acc2": Acc2, "Prec2": Prec2, "Recll2": Recll2, "F2": F2, 
					"Acc3": Acc3, "Prec3": Prec3, "Recll3": Recll3, "F3": F3, 
					"Acc4": Acc4, "Prec4": Prec4, "Recll4": Recll4, "F4": F4, 
				}

		fw.write("{:4d}\t{:.0E}\t{:.0E}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\t{:.4f}\n".format(
			self.args.foldnum, self.args.learningRate, self.args.learningRateGraph, self.args.dropout_gat, best_metrics["Acc."] , best_metrics["macroF"], 
			best_metrics["Acc1"], best_metrics["Prec1"], best_metrics["Recll1"], best_metrics["F1"],
			best_metrics["Acc2"], best_metrics["Prec2"], best_metrics["Recll2"], best_metrics["F2"],
			best_metrics["Acc3"], best_metrics["Prec3"], best_metrics["Recll3"], best_metrics["F3"],
			best_metrics["Acc4"], best_metrics["Prec4"], best_metrics["Recll4"], best_metrics["F4"]
		))

	def run(self):
		self.train()

def main():
	parser = argparse.ArgumentParser()

	#Required parameters
	parser.add_argument("--seed", type=int, default=42, help="random seed number for initialization")
	parser.add_argument("--mode", default="DUCK", type=str, help="pick from CommentTree, UserTree or DUCK")
	parser.add_argument("--baseDirectory", type=str, default=".", help="the data directory")
	parser.add_argument("--foldnum", default=0, type=int, help="The fold number to test out")
	parser.add_argument("--datasetName", default=None, type=str, required=True, help="The name of the dataset to play with")
	parser.add_argument("--n_classes", default=4, type=int, help="4 for Twitter15/Twitter16, 3 for semeval2019")
	parser.add_argument("--result_path", type=str, default="./result")

	#Hyper-parameters
	parser.add_argument("--bertVersion", default="bert-base-uncased", type=str, help="set up the bert version")
	parser.add_argument("--weight_decay", default=0.0, type=float, help="the weight decay")
	parser.add_argument("--learningRate", default=5e-5, type=float, help="the initial learning rate")
	parser.add_argument("--learningRateGraph", default=1e-5, type=float, help="the inital learning rate for GNN")
	parser.add_argument("--patience"    , default= 10, type=int, help="early stop patience")
	parser.add_argument("--n_epochs"    , default= 10, type=int, help="fine tuning epoches")
	parser.add_argument("--batchsize"   , default=256, type=int, help="batch size")
	parser.add_argument("--multi_gpu"   , default=  0, type=int, help="number of GPUs")
	parser.add_argument("--dropout_gat" , default=0.5, type=float)
	parser.add_argument("--max_tree_len", default=1000, type=int, help="maximum tree length, for less GPU memory during training")

	#pick up the model to play with
	parser.add_argument("--modelName", default=None, required=True, type=str, help="pick up the model to play with")

	args = parser.parse_args()

	duck = DUCK(args)
	duck.run()

if __name__ == '__main__':
	main()
