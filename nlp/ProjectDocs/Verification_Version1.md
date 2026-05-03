Summary of Required Revisions
Overall, the report is well-structured, methodologically careful, and scientifically honest. However, several issues should be addressed before final submission to better comply with the project guidelines.

High-Priority Revisions
Reduce the report length to 4–6 pages.
The current report is 8 pages, which exceeds the guideline requirement. The experiment command list, detailed dataset statistics, large figures, and PDF export appendix should be shortened or moved to an appendix/repository README.
Revise or justify the literature review sources.
The guidelines appear to emphasize papers from major NLP venues such as ACL, NAACL, and EMNLP. Two cited papers are from SIGDIAL and NLP4DH/workshop venues. These should either be replaced with papers from the required venues or explicitly justified as relevant supporting sources.
Strengthen the critique in the related work section.
The current literature review mostly summarizes prior studies. Each cited paper should include a brief critique, such as its methodological limitation, data limitation, or why it does not fully address this project’s research question.
Medium-Priority Revisions
Add more experimental variation.
The LSTM is currently tested in only one configuration. The report should include at least one additional LSTM variant, such as a different number of hidden units, dropout, number of layers, or sequence length. This would better satisfy the guideline expectation for experimentation across architectures, hyperparameters, or techniques.
Discuss the bigram Naive Bayes result.
The bigram NB model performs slightly worse than the unigram NB model, but the report does not explain why. Add a short discussion noting possible causes such as data sparsity, small sample size, short informal comments, or vocabulary mismatch across match-aware splits.
Clarify dataset provenance and reproducibility.
The report should explain that the corpus was self-constructed from publicly accessible HLTV-style match threads rather than taken from a standard public dataset. It should also address compliance with site terms, what data can be shared, and how the pipeline can be reproduced.
Lower-Priority Revisions
Add a per-class precision/recall/F1 table.
Because the dataset is highly imbalanced and negative sentiment is difficult to classify, a small per-class performance table would make the evaluation clearer than relying only on macro-F1 and confusion matrices.
Make the title and claims more conservative.
Since the momentum correlations are near zero, the title and wording should avoid implying that the model successfully predicts momentum shifts. A title such as “Evaluating Temporal Sentiment as a Signal for Momentum Shifts in Competitive Esports” would better match the findings.
Condense the methodology details.
Keep the core methodological explanation, but remove excessive implementation details such as full command lines. These can be referenced as part of the repository artifact instead.
Preserve the strongest parts of the report.
The match-aware split, dual weak/gold-label evaluation, honest reporting of near-zero momentum correlations, and clear figures should be kept because they are strong methodological and scientific contributions.