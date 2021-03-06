import os
from os.path import join, exists
import fire
import numpy as np
import pandas as pd
from pyfaidx import Fasta
from collections import Counter
import RNA

from fisheye.utils import get_logger


log = get_logger(__name__)


def read_gene(genelist):
    genelist = pd.read_csv(genelist,header = None)
    genelist.columns = ['geneID']
    return genelist

def read_gtf(gtf):
    log.info("Reading gtf: " + gtf)
    df = pd.read_csv(gtf, sep='\t', header=None)
    df.columns = ['chr', 'source', 'type', 'start', 'end', 'X1', 'strand', 'X2', 'fields']
    df['gene_name'] = df.fields.str.extract("gene_name \"(.*?)\"")
    df['length'] = df['end'] - df['start']
    return df

###################################################
def get_base_map():
    base_map = [b'\0' for i in range(256)]
    base_map[ ord('A') ] = b'T'
    base_map[ ord('T') ] = b'A'
    base_map[ ord('C') ] = b'G'
    base_map[ ord('G') ] = b'C'
    base_map[ ord('a') ] = b't'
    base_map[ ord('t') ] = b'a'
    base_map[ ord('c') ] = b'g'
    base_map[ ord('g') ] = b'c'
    base_map[ ord('N') ] = b'N'
    base_map[ ord('n') ] = b'n'
    base_map = bytes(b''.join(base_map))
    return base_map

BASEMAP = get_base_map()
def reverse_complement(seq):
    res = seq[::-1]
    res = res.translate(BASEMAP)
    return res

def sequence_pickup(df_gtf, fa, genelist, min_length=40 ):
    seq_lst = {}
    for item in genelist.iterrows():
        name = item[1]['geneID']
        df_gene = df_gtf[df_gtf.gene_name == name]
        df_cds = df_gene[df_gene.type == 'CDS'].copy()
        df_cds = df_cds[df_cds.length > min_length]
        cds_cnts = df_cds.groupby(by=['chr', 'start', 'end', "length", "strand"], as_index=False).count()
        cnts_max = cds_cnts[cds_cnts['type'] == cds_cnts['type'].max()]
        cds_select = cnts_max[cnts_max['length'] == cnts_max['length'].max()]
        chr_, start, end, strand = cds_select.iloc[0].chr, cds_select.iloc[0].start, cds_select.iloc[0].end, \
                                   cds_select.iloc[0].strand
        seq = fa[chr_][start:end].seq
        if strand == '-':
            seq = reverse_complement(seq)
        seq_lst[name] = seq
    return seq_lst

#####################################################
def self_match(probe, min_match = 4):
    length = len(probe)
    probe_re = reverse_complement(probe)
    match_pairs = 0
    for i in range(0,length-min_match+1):
        tem = probe[i:min_match+i]
        for j in range(0,length-min_match+1):
            tem_re = probe_re[j:min_match+j]
            if tem == tem_re and i + j + min_match - 2 != length:
                match_pairs = match_pairs + 1
    return match_pairs

def normalization(match_pairs_pad, match_pairs_amp, region, fold_score):
    # 让值有参考意义
    value = np.array([match_pairs_pad, match_pairs_amp, region, fold_score])
    value_mean = value.mean(axis=0)
    value_std = value.std(axis=0)
    conbined_score = np.sum((value-value_mean)/value_std)
    return conbined_score

def primer_design(seq, min_length=40):
    df_lst = []
    seq_len = len(seq)
    for i in range(0,len(seq)-min_length+1):
        tem = seq[i:min_length+i]
        fold_score = round(RNA.fold_compound(tem).mfe()[1],2)
        tem1 = tem[0:13]
        tem2 = tem[13:26]
        tem3 = tem[27:40]
        tem4 = tem[26]
        cg1 = Counter(tem1)["G"] + Counter(tem1)["C"] # use primer3 or biopython
        cg2 = Counter(tem2)["G"] + Counter(tem2)["C"]
        cg3 = Counter(tem3)["G"] + Counter(tem3)["C"]
        tm1 = 2 * (13 - cg1) + 4 * cg1
        tm2 = 2 * (13 - cg2) + 4 * cg2
        tm3 = 2 * (14 - cg3) + 4 * cg3
        region = max(tm1,tm2,tm3) - min(tm1,tm2,tm3)
        tem1_re = reverse_complement(tem1)
        tem2_re = reverse_complement(tem2)
        tem3_re = reverse_complement(tem3)
        pad_probe = tem1_re+"CCAGTGCGTCTATTTAGTGGAGCCTGCAGT"+tem2_re
        amp_probe = tem3_re+tem4+"ACTGCAGGCTCCA"
        match_pairs_pad = self_match(pad_probe)
        match_pairs_amp = self_match(amp_probe)
        conbined_score = normalization(match_pairs_pad, match_pairs_amp, region, fold_score)
        df_lst.append([match_pairs_pad, match_pairs_amp, region, tm1, tm2, tm3, fold_score, conbined_score, pad_probe, amp_probe])
    df = pd.DataFrame(df_lst)
    df.columns = ['point1', 'point2', 'tm_region', 'tm1', 'tm2', 'tm3', 'RNAfold_score', 'conbined_score','primer1', 'primer2']
    df.sort_values(['conbined_score'])
    return df


def main(genelist, gtf, fasta, output_dir="primers"):
    """
    input: genelist gtf fasta
    output: results/{gene}.csv
    """
    fa = Fasta(fasta)
    genelist = read_gene(genelist)
    df_gtf = read_gtf(gtf)
    seq_lst = sequence_pickup(df_gtf, fa, genelist, min_length=40)
    if not exists(output_dir):
        os.mkdir(output_dir)
    for name, seq in seq_lst.items():
        log.info("Designing primer for gene " + name + ":")
        res_df = primer_design(seq)
        out_path = join(output_dir, f"{name}.csv")
        log.info("Save results to: " + out_path)
        res_df.to_csv(out_path)


fire.Fire(main)

