# EvaliSense

## Project name
EvaliSense: AI-Powered Handwritten Examination Evaluation with ML-Based Grading Error Prediction

## Project purpose
EvaliSense is an examiner-assistance system designed to support the evaluation of handwritten examination answers. It does not replace teachers or examiners. The system is intended to assist with a structured, transparent, and auditable evaluation workflow in which a human examiner remains responsible for the final mark.

## Core research question
Can machine learning predict when an AI-based handwritten examination grading system is likely to produce a significant grading error?

## High-level pipeline
1. Handwritten examination answer images are collected and prepared for processing.
2. Image preprocessing and document cleaning are applied to improve recognition quality.
3. HTR/OCR is used to obtain machine-readable text from handwritten responses.
4. The extracted text is evaluated using semantic and rubric-based assessment logic.
5. A preliminary AI-generated mark is produced for the response.
6. Features are extracted from the recognition, evaluation, and document-processing pipeline.
7. A separate supervised machine learning model predicts whether a grading outcome is at high risk of significant error.
8. High-risk cases are flagged for human examiner review.
9. The examiner remains the final authority.

## Current development status
This repository is in the initial project scaffolding stage. The core system components are not yet implemented.

The following components are planned as modular, independently testable units:
- preprocessing
- htr
- evaluation
- features
- models

Current implementation focus:
- project structure and repository setup
- documentation and modular architecture
- environment initialization

Important constraints:
- HTR/OCR is not yet implemented.
- AI grading is not yet implemented.
- The ML grading-error predictor is not yet implemented.
- No model results, accuracy values, or fabricated evaluation outcomes are included in this repository.

## Architectural principle
The project is intentionally modular so that preprocessing, handwriting recognition, answer evaluation, feature extraction, and grading-error prediction can be developed and tested independently before integration.

## Examiner authority
The examiner remains the final authority.

## Image Preprocessing
Handwritten answer preprocessing is a required stage before HTR/OCR. The preprocessing module prepares scanned or photographed examination responses for downstream recognition by reducing noise, improving contrast, standardizing intensity, and correcting simple geometric distortions when useful.

The current implementation includes configurable image loading, grayscale conversion, denoising, contrast enhancement, thresholding, and optional deskewing. These operations are designed to be reusable and modular so the preprocessing stage can be tested independently before the HTR pipeline is added.

The exact settings may vary depending on handwriting quality, image capture conditions, and dataset characteristics. Preprocessing is intended to improve the input quality for subsequent recognition tasks, but it does not guarantee better HTR accuracy in all cases.

### Command-line demonstration
A simple preprocessing demo can be run with a handwritten answer image:

```bash
python preprocessing_demo.py --input path/to/answer.jpg --output data/processed/answer_processed.png
```

This saves the final processed image and keeps the preprocessing stage separate from future HTR and grading components.

## Handwritten Text Recognition

HTR converts handwritten examination content into machine-readable text. Because the development input is a full notebook page, the baseline first segments the page into ordered candidate text lines and then applies line-level recognition. Segmentation and recognition are separate modules so they can be improved or replaced independently.

This repository contains a pretrained TrOCR baseline (`microsoft/trocr-base-handwritten`) for development experimentation. The HTR architecture is configurable and is not considered permanently finalized. Recognition quality will be evaluated experimentally later; this single sample is not a formal accuracy evaluation, and the system does not assume HTR output is always correct.

The optional confidence value is derived from the geometric mean of the generated-token probabilities returned by the model. It is an uncalibrated development signal and is kept separate from recognized text because it may become a candidate feature for future grading-error prediction.

The baseline can compare raw and preprocessed inputs:

```bash
python htr_demo.py --input data/raw/test_answer.jpg --output experiments/htr_baseline/raw --debug-lines
python htr_demo.py --input data/processed/test_answer_processed.png --output experiments/htr_baseline/processed --debug-lines
```

Use a separate Python 3.13 environment for HTR on this Windows setup because the original environment uses Python 3.14 and the selected ML dependency stack may not provide compatible builds there. Install the dependencies from `requirements.txt` into that environment. The model is downloaded through the normal Hugging Face cache and is not stored in this repository.

This is a **baseline implementation / experimentation** stage only. It does not implement semantic evaluation, rubric scoring, marking, or grading-error prediction. Human examiners remain the final authority.

## Repository structure
The project currently includes the planned directories for data, preprocessing, HTR, evaluation, features, models, experiments, utilities, API, notebooks, tests, and project-level configuration.
