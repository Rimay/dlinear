from models import MoLE_DLinear, MoLE_RLinear, MoLE_RMLP
from data_provider.data_factory import data_provider
from utils.tools import EarlyStopping, adjust_learning_rate, test_params_flop
from utils.metrics import metric as get_metric

import numpy as np
import torch
import torch.nn as nn
from torch import optim
from utils.augmentations import augmentation
import os
import time

import warnings
import numpy as np

warnings.filterwarnings('ignore')

class Exp_Main(object):
    def __init__(self, args):
        super(Exp_Main, self).__init__()
        self.args = args
        self.device = None
        if self.args.use_gpu:
            os.environ["CUDA_VISIBLE_DEVICES"] = str(
                self.args.gpu) if not self.args.use_multi_gpu else self.args.devices
            self.device = torch.device('cuda:{}'.format(self.args.gpu))
            print('Use GPU: cuda:{}'.format(self.args.gpu))
        else:
            self.device = torch.device('cpu')
            print('Use CPU')

        model_dict = {
            'MoLE_DLinear': MoLE_DLinear,
            'MoLE_RLinear': MoLE_RLinear,
            'MoLE_RMLP': MoLE_RMLP,
        }
        self.model = model_dict[self.args.model].Model(self.args).float()
        if self.args.use_multi_gpu and self.args.use_gpu:
            self.model = nn.DataParallel(self.model, device_ids=self.args.device_ids)

    def vali(self, vali_loader, criterion):
        total_loss = []
        self.model.eval()
        with torch.no_grad():
            for _, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(vali_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float()

                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)
                
                # encoder - decoder
                if 'MoLE' in self.args.model and ('Linear' in self.args.model or 'MLP' in self.args.model):
                    outputs = self.model(batch_x, batch_x_mark)
                elif 'former' not in self.args.model:
                    outputs = self.model(batch_x)
                elif self.args.output_attention:
                    outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)[0]
                else:
                    outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)
                f_dim = -1 if self.args.features == 'MS' else 0
                outputs = outputs[:, -self.args.pred_len:, f_dim:]
                batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)

                pred = outputs.detach().cpu()
                true = batch_y.detach().cpu()
                loss = criterion(pred, true)
                total_loss.append(loss)

        # print(total_loss)
        total_loss = np.average(total_loss)
        self.model.train()
        return total_loss

    def train(self, setting, ft=True):
        train_data, train_loader = data_provider(self.args, flag='train')
        vali_data, vali_loader = data_provider(self.args, flag='val')
        test_data, test_loader = data_provider(self.args, flag='test')

        path = os.path.join(self.args.checkpoints, setting)
        if not os.path.exists(path):
            os.makedirs(path)

        time_now = time.time()
        train_steps = len(train_loader)
        early_stopping = EarlyStopping(patience=self.args.patience, verbose=True)
        model_optim = optim.Adam(self.model.parameters(), lr=self.args.learning_rate)
        criterion = nn.MSELoss()

        for epoch in range(self.args.train_epochs):
            iter_count = 0
            train_loss = []

            self.model.train()
            epoch_time = time.time()
            if self.args.in_dataset_augmentation:
                train_loader.dataset.regenerate_augmentation_data()

            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(train_loader):
                iter_count += 1
                model_optim.zero_grad()

                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)
                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)
                batch_xy = torch.cat([batch_x, batch_y[:,-self.args.pred_len:,:]], dim=1)

                if self.args.in_batch_augmentation:
                    aug = augmentation('batch')
                    methods = {'f_mask':aug.freq_mask, 'f_mix': aug.freq_mix, 'noise': aug.noise, 'warp': aug.warping, 'flip': aug.flipping, 'mask': aug.masking, 'mask_seg': aug.masking_seg, 'noise_input':aug.noise_input}
                        
                    if self.args.wo_original_set:
                        xy = methods[self.args.aug_method](batch_x, batch_y[:, -self.args.pred_len:, :], rate=self.args.aug_rate)
                        batch_x, batch_y = xy[:, :self.args.seq_len, :], xy[:, -self.args.label_len-self.args.pred_len:, :]
                    else:
                        for step in range(self.args.aug_data_size):
                            xy = methods[self.args.aug_method](batch_x, batch_y[:, -self.args.pred_len:, :], rate=self.args.aug_rate)
                            batch_x2, batch_y2 = xy[:, :self.args.seq_len, :], xy[:, -self.args.label_len-self.args.pred_len:, :]
                            batch_x = torch.cat([batch_x,batch_x2],dim=0)
                            batch_y = torch.cat([batch_y,batch_y2],dim=0)
                            batch_x_mark = torch.cat([batch_x_mark,batch_x_mark],dim=0)
                            batch_y_mark = torch.cat([batch_y_mark,batch_y_mark],dim=0)
                        
                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)

                # encoder - decoder
                if 'MoLE' in self.args.model and ('Linear' in self.args.model or 'MLP' in self.args.model):
                    outputs = self.model(batch_x, batch_x_mark)
                elif 'former' not in self.args.model:
                    outputs = self.model(batch_x)
                elif self.args.output_attention:
                    outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)[0]
                else:
                    outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark, batch_y)

                # print(outputs.shape,batch_y.shape)
                f_dim = -1 if self.args.features == 'MS' else 0
                if ft:
                    outputs = outputs[:, -self.args.pred_len:, f_dim:]
                    batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)
                    loss = criterion(outputs, batch_y)
                else:
                    outputs = outputs[:, :, f_dim:]
                    loss = criterion(outputs, batch_xy)
                train_loss.append(loss.item())

                if (i + 1) % 100 == 0:
                    print("\titers: {0}, epoch: {1} | loss: {2:.7f}".format(i + 1, epoch + 1, loss.item()))
                    speed = (time.time() - time_now) / iter_count
                    left_time = speed * ((self.args.train_epochs - epoch) * train_steps - i)
                    print('\tspeed: {:.4f}s/iter; left time: {:.4f}s'.format(speed, left_time))
                    iter_count = 0
                    time_now = time.time()

                loss.backward()
                model_optim.step()

            print("Epoch: {} cost time: {}".format(epoch + 1, time.time() - epoch_time))
            train_loss = np.average(train_loss)
            vali_loss = self.vali(vali_loader, criterion)
            test_loss = self.vali(test_loader, criterion)

            print("Epoch: {0}, Steps: {1} | Train Loss: {2:.7f} Vali Loss: {3:.7f} Test Loss: {4:.7f}".format(
                            epoch + 1, train_steps, train_loss, vali_loss, test_loss))
            early_stopping(vali_loss, self.model, path)
            if early_stopping.early_stop:
                print("Early stopping")
                break
            if self.args.lradj != 'TST':
                adjust_learning_rate(model_optim, None, epoch + 1, self.args)

        best_model_path = path + '/' + 'checkpoint.pth'
        self.model.load_state_dict(torch.load(best_model_path))

        return self.model

    def test(self, setting, test=0, flag='test', fixed_head=None, seperate_head=False):
        test_data, test_loader = data_provider(self.args, flag=flag)
        
        if test:
            print('loading model')
            self.model.load_state_dict(torch.load(os.path.join('./checkpoints/' + setting, 'checkpoint.pth')))

        preds = []
        trues = []
        inputx = []
        time_embeds = []
        folder_path = './test_results/' + setting + '/'
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        self.model.eval()
        with torch.no_grad():
            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(test_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float().to(self.device)

                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros_like(batch_y[:, -self.args.pred_len:, :]).float()
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)
                # encoder - decoder
                
                if 'MoLE' in self.args.model and ('Linear' in self.args.model or 'MLP' in self.args.model):
                    if self.args.save_gating_weights:
                        outputs, gating_weights = self.model(batch_x, batch_x_mark)
                        time_embeds.append(gating_weights.detach().cpu().numpy())
                    else:
                        outputs = self.model(batch_x, batch_x_mark, return_seperate_head=seperate_head or fixed_head is not None)
                elif 'former' not in self.args.model:
                        outputs = self.model(batch_x)
                else:
                    if self.args.output_attention:
                        outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)[0]

                    else:
                        outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)

                f_dim = -1 if self.args.features == 'MS' else 0
                # print(outputs.shape,batch_y.shape)
                outputs = outputs[:, -self.args.pred_len:, f_dim:]
                batch_y = batch_y[:, -self.args.pred_len:, f_dim:].to(self.device)
                outputs = outputs.detach().cpu().numpy()
                batch_y = batch_y.detach().cpu().numpy()

                pred = outputs  # outputs.detach().cpu().numpy()  # .squeeze()
                true = batch_y  # batch_y.detach().cpu().numpy()  # .squeeze()

                preds.append(pred)
                trues.append(true)
                inputx.append(batch_x.detach().cpu().numpy())

        if self.args.test_flop:
            test_params_flop((batch_x.shape[1],batch_x.shape[2]))
            exit()
        preds = np.array(preds)
        trues = np.array(trues)
        inputx = np.array(inputx)

        if seperate_head or fixed_head is not None:
            preds = preds.reshape(-1, preds.shape[-3], preds.shape[-2], preds.shape[-1])
        else:
            preds = preds.reshape(-1, preds.shape[-2], preds.shape[-1])
        trues = trues.reshape(-1, trues.shape[-2], trues.shape[-1])
        inputx = inputx.reshape(-1, inputx.shape[-2], inputx.shape[-1])

        # result save
        folder_path = './results/' + setting + '/'
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        if seperate_head:
            metrics = []
            for pred_index in range(preds.shape[-1]):
                metrics.append(get_metric(preds[:,:,:,pred_index], trues))
            lowest_metric = None
            lowest_index = None
            for i, metric in enumerate(metrics):
                if lowest_metric is None or lowest_metric > metric:
                    lowest_metric = metric
                    lowest_index = i
            mae, mse, rmse, mape, mspe, rse, corr = lowest_metric
        elif fixed_head is not None:
            mae, mse, rmse, mape, mspe, rse, corr = get_metric(preds[:,:,:,fixed_head], trues)
        else:
            mae, mse, rmse, mape, mspe, rse, corr = get_metric(preds, trues)
        print('mse:{}, mae:{}, rse:{}'.format(mse, mae, rse))
        f = open("result.txt", 'a')
        f.write(setting + "  \n")
        f.write('mse:{}, mae:{}, rse:{}, corr:{}'.format(mse, mae, rse, corr))
        f.write('\n')
        f.write('\n')
        f.close()

        if False:
            np.save(folder_path + f'metrics_{flag}.npy', np.array([mae, mse, rmse, mape, mspe,rse, corr]))
            np.save(folder_path + f'pred.npy_{flag}', preds)
            np.save(folder_path + f'true_{flag}.npy', trues)
            np.save(folder_path + f'x_{flag}.npy', inputx)
        
        if time_embeds:
            time_embeds = np.concatenate(time_embeds, axis=0)
            np.save(self.args.save_gating_weights, time_embeds)
        
        if seperate_head:
            return lowest_index
        return

    def predict(self, setting, load=False):
        pred_data, pred_loader = data_provider(self.args, flag='pred')

        if load:
            path = os.path.join(self.args.checkpoints, setting)
            best_model_path = path + '/' + 'checkpoint.pth'
            self.model.load_state_dict(torch.load(best_model_path))

        preds = []

        self.model.eval()
        with torch.no_grad():
            for i, (batch_x, batch_y, batch_x_mark, batch_y_mark) in enumerate(pred_loader):
                batch_x = batch_x.float().to(self.device)
                batch_y = batch_y.float()
                batch_x_mark = batch_x_mark.float().to(self.device)
                batch_y_mark = batch_y_mark.float().to(self.device)

                # decoder input
                dec_inp = torch.zeros([batch_y.shape[0], self.args.pred_len, batch_y.shape[2]]).float().to(batch_y.device)
                dec_inp = torch.cat([batch_y[:, :self.args.label_len, :], dec_inp], dim=1).float().to(self.device)
                # encoder - decoder
                if 'MoLE' in self.args.model and ('Linear' in self.args.model or 'MLP' in self.args.model):
                    outputs = self.model(batch_x, batch_x_mark)
                elif 'former' not in self.args.model:
                        outputs = self.model(batch_x)
                else:
                    if self.args.output_attention:
                        outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)[0]
                    else:
                        outputs = self.model(batch_x, batch_x_mark, dec_inp, batch_y_mark)
                pred = outputs.detach().cpu().numpy()  # .squeeze()
                preds.append(pred)

        preds = np.array(preds)
        preds = preds.reshape(-1, preds.shape[-2], preds.shape[-1])

        # result save
        folder_path = './results/' + setting + '/'
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        np.save(folder_path + 'real_prediction.npy', preds)

        return