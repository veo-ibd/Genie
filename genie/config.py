from .bed import bed
from .bedSP import bedSP
from .workflow import workflow
from .clinical import clinical
from .seg import seg
from .cbs import cbs
from .maf import maf
from .mafSP import mafSP
from .clinicalSP import clinicalSP
from .vcf import vcf
from .cna import cna
from .fusions import fusions
from .sampleRetraction import sampleRetraction
from .patientRetraction import patientRetraction
# from .patientCounts import patientCounts
from .mutationsInCis import mutationsInCis
# from .vitalStatus import vitalStatus
from .assay import Assayinfo

PROCESS_FILES = {'bed': bed,
                 'bedSP': bedSP,
                 'maf': maf,
                 'mafSP': mafSP,
                 'clinical': clinical,
                 'clinicalSP': clinicalSP,
                 'vcf': vcf,
                 'cbs': cbs,
                 'cna': cna,
                 'fusions': fusions,
                 'md': workflow,
                 'seg': seg,
                 'patientRetraction': patientRetraction,
                 'sampleRetraction': sampleRetraction,
                 # 'patientCounts': patientCounts,
                 'mutationsInCis': mutationsInCis,
                 # 'vitalStatus': vitalStatus,
                 'assayinfo': Assayinfo}
