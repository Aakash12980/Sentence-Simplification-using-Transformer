import click
import pickle
import os
import torch
import numpy as np
from torch.utils.data import DataLoader
from data import WikiDataset
from tokenizer import Tokenizer
from model import EncDecModel
from nltk.translate.bleu_score import corpus_bleu, SmoothingFunction
import time
import tqdm
import logging
import gc

TRAIN_BATCH_SIZE = 4
N_EPOCH = 5
max_token_len = 80
LOG_EVERY = 10000

logging.basicConfig(filename="./drive/My Drive/Mini Project/log_file.log", level=logging.INFO, 
                format="%(asctime)s:%(levelname)s: %(message)s")
CONTEXT_SETTINGS = dict(help_option_names = ['-h', '--help'])

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using {device} as device")

def collate_fn(batch):
    data_list, label_list = [], []
    for _data, _label in batch:
        data_list.append(_data)
        label_list.append(_label)
    return data_list, label_list

def compute_bleu_score(logits, labels):
    refs = Tokenizer.get_sent_tokens(labels)
    weights = (1.0/2.0, 1.0/2.0, )
    score = corpus_bleu(refs, logits.tolist(), smoothing_function=SmoothingFunction(epsilon=1e-10).method1, weights=weights)
    return score

def evaluate(data_loader, e_loss, model):
    was_training = model.training
    model.eval()
    eval_loss = e_loss
    bleu_score = 0

    with torch.no_grad():
        for step, batch in enumerate(data_loader):
            loss, logits = model(batch, device, False)
            score = compute_bleu_score(logits, batch[1])
            if step == 0:
                eval_loss = loss.item()
                bleu_score = score
            else:
                eval_loss = (1/2.0)*(eval_loss + loss.item())
                bleu_score = (1/2.0)* (bleu_score+score) 
        
    if was_training:
        model.train()

    return eval_loss, bleu_score 


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version = '1.0.0')
def task():
    ''' This is the documentation of the main file. This is the reference for executing this file.'''
    pass


@task.command()
@click.option('--src_train', default="./drive/My Drive/Mini Project/dataset/src_train.txt", help="train source file path")
@click.option('--tgt_train', default="./drive/My Drive/Mini Project/dataset/tgt_train.txt", help="train target file path")
@click.option('--src_valid', default="./drive/My Drive/Mini Project/dataset/src_valid.txt", help="validation source file path")
@click.option('--tgt_valid', default="./drive/My Drive/Mini Project/dataset/tgt_valid.txt", help="validation target file path")
@click.option('--best_model', default="./drive/My Drive/Mini Project/best_model/model.pt", help="best model file path")
@click.option('--checkpoint_path', default="./drive/My Drive/Mini Project/checkpoint/model_ckpt.pt", help=" model check point files path")
@click.option('--seed', default=123, help="manual seed value (default=123)")
def train(**kwargs):
    print("Loading datasets...")
    train_dataset = WikiDataset(kwargs['src_train'], kwargs['tgt_train'])
    valid_dataset = WikiDataset(kwargs['src_valid'], kwargs['tgt_valid'])
    print("Dataset loaded successfully")

    train_dl = DataLoader(train_dataset, batch_size=TRAIN_BATCH_SIZE, collate_fn=collate_fn, shuffle=True)
    valid_dl = DataLoader(valid_dataset, batch_size=TRAIN_BATCH_SIZE, collate_fn=collate_fn, shuffle=True)

    model = EncDecModel(max_token_len)
    model.to(device)
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'gamma', 'beta']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
        'weight_decay_rate': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)],
        'weight_decay_rate': 0.0}
    ]
    optimizer = torch.optim.AdamW(optimizer_grouped_parameters, lr=3e-5)
    start_epoch = 0
    eval_loss = float("inf")

    if os.path.exists(kwargs["checkpoint_path"]):
        optimizer, eval_loss, start_epoch = model.load_model(kwargs["checkpoint_path"], device, optimizer)
        print(f"Loading model from checkpoint with start epoch: {start_epoch} and loss: {eval_loss}")
        logging.info(f"Model loaded from saved checkpoint with start epoch: {start_epoch} and loss: {eval_loss}")
    

    train_model(start_epoch, eval_loss, (train_dl, valid_dl), optimizer, kwargs["checkpoint_path"], kwargs["best_model"], model)

@task.command()
@click.option('--src_test', default="./drive/My Drive/Mini Project/dataset/src_test.txt", help="test source file path")
@click.option('--tgt_test', default="./drive/My Drive/Mini Project/dataset/tgt_test.txt", help="test target file path")
@click.option('--best_model', default="./drive/My Drive/Mini Project/best_model/model.pt", help="best model file path")
def test(**kwargs):
    print("Testing Model module executing...")
    logging.info(f"Test module invoked.")
    model = EncDecModel(max_token_len)
    _, _, _ = model.load_model(kwargs["best_model"], device)
    print(f"Model loaded.")
    model.to(device)
    model.eval()
    test_dataset = WikiDataset(kwargs['src_test'], kwargs['tgt_test'])
    test_dl = DataLoader(test_dataset, batch_size=TRAIN_BATCH_SIZE, collate_fn=collate_fn, shuffle=True)
    test_start_time = time.time()
    test_loss, bleu_score = evaluate(test_dl, 0, model)
    test_loss = test_loss/TRAIN_BATCH_SIZE
    bleu_score = bleu_score/TRAIN_BATCH_SIZE
    print(f'Avg. eval loss: {test_loss:.5f} | blue score: {bleu_score} | time elapsed: {time.time() - test_start_time}')
    logging.info(f'Avg. eval loss: {test_loss:.5f} | blue score: {bleu_score} | time elapsed: {time.time() - test_start_time}')
    print("Test Complete!")
    

@task.command()
@click.option('--src_file', default="./drive/My Drive/Mini Project/dataset/src_file.txt", help="test source file path")
@click.option('--best_model', default="./drive/My Drive/Mini Project/best_model/model.pt", help="best model file path")
@click.option('--output', default="./drive/My Drive/Mini Project/outputs/decoded.txt", help="file path to save predictions")
def decode(**kwargs):
    print("Decoding sentences module executing...")
    logging.info(f"Decode module invoked.")
    enc_dec_model = EncDecModel(max_token_len)
    _, _, _ = enc_dec_model.load_model(kwargs["best_model"], device)
    print(f"Model loaded.")
    enc_dec_model.to(device)
    enc_dec_model.eval()
    dataset = WikiDataset(kwargs['src_file'])
    predicted_list = []
    sent_tensors = enc_dec_model.tokenizer.encode_sent(dataset.src)
    print("Decoding Sentences...")
    for sent in sent_tensors:
        with torch.no_grad():
            print(f"input: {sent[0].size()}")
            predicted = enc_dec_model.model.generate(sent[0].to(device), attention_mask=sent[1].to(device))
            print(f'output: {predicted.squeeze().size()}')
            predicted_list.append(predicted.squeeze())
    
    output = enc_dec_model.tokenizer.decode_sent_tokens(predicted_list)
    with open(kwargs["output"], "w") as f:
        for sent in output:
            f.write(sent + "\n")
    print("Output file saved successfully.")


def train_model(start_epoch, eval_loss, loaders, optimizer, check_pt_path, best_model_path, model):
    best_eval_loss = eval_loss
    print("Model training started...")
    for epoch in range(start_epoch, N_EPOCH):
        print(f"Epoch {epoch} running...")
        epoch_start_time = time.time()
        epoch_train_loss = 0
        epoch_eval_loss = 0
        model.train()
        for step, batch in enumerate(loaders[0]):
            optimizer.zero_grad()
            model.zero_grad()
            loss = model(batch, device)
            if step == 0:
                epoch_train_loss = loss.item()
            else:
                epoch_train_loss = (1/2.0)*(epoch_train_loss + loss.item())
            
            loss.backward()
            optimizer.step()

            if (step+1) % LOG_EVERY == 0:
                print(f'Epoch: {epoch} | iter: {step+1} | avg. train loss: {epoch_train_loss/TRAIN_BATCH_SIZE} | time elapsed: {time.time() - epoch_start_time}')
                logging.info(f'Epoch: {epoch} | iter: {step+1} | avg. train loss: {epoch_train_loss/TRAIN_BATCH_SIZE} | time elapsed: {time.time() - epoch_start_time}')
                eval_start_time = time.time()
                epoch_eval_loss, bleu_score = evaluate(loaders[1], epoch_eval_loss, model)
                epoch_eval_loss = epoch_eval_loss/TRAIN_BATCH_SIZE
                bleu_score = bleu_score/TRAIN_BATCH_SIZE
                print(f'Completed Epoch: {epoch} | avg. eval loss: {epoch_eval_loss:.5f} | blue score: {bleu_score} | time elapsed: {time.time() - eval_start_time}')
                logging.info(f'Completed Epoch: {epoch} | avg. eval loss: {epoch_eval_loss:.5f} | blue score: {bleu_score} | bleu score: {bleu_score} | time elapsed: {time.time() - eval_start_time}')
        
                check_pt = {
                    'epoch': epoch+1,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'eval_loss': epoch_eval_loss
                }
                check_pt_time = time.time()
                print("Saving Checkpoint.......")
                if epoch_eval_loss < best_eval_loss:
                    print("New best model found")
                    logging.info(f"New best model found")
                    best_eval_loss = epoch_eval_loss
                    model.save_checkpt(check_pt, True, check_pt_path, best_model_path)
                else:
                    model.save_checkpt(check_pt, False, check_pt_path, best_model_path)  
                print(f"Checkpoint saved successfully with time: {time.time() - check_pt_time}")
                logging.info(f"Checkpoint saved successfully with time: {time.time() - check_pt_time}")

    gc.collect()
    torch.cuda.empty_cache()  


if __name__ == "__main__":
    task()