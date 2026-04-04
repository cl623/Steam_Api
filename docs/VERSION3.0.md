This roadmap outlines the technical transition from your current **Banded Random Forest/Gradient Boosting** architecture to a **Sequential Deep Learning (LSTM/GRU)** model.

Here is the updated, merged roadmap. This acts as your official transition plan into Version 3.0 (Deep Learning), taking the most strategic concepts from your V2.5 plan and integrating them directly into the neural network architecture.

This roadmap is exactly what you can use to guide your coding over the next few weeks and present to your professor.

---

# Version 3.0 Roadmap: Sequential Deep Learning (LSTM)

## Context & Baseline

With Version 2 completed, the backtesting environment now includes liquidity-grounded trade sizing, deduplication, and a $1.00 minimum price floor. Crucially, Milestone 5 of the V2.5 roadmap (Target Transformation to Log Returns) is already complete. The traditional ML baselines (Random Forest and Gradient Boosting) have hit a structural wall regarding temporal memory and extreme outlier extrapolation.

The next phase shifts entirely to Deep Learning (PyTorch), natively absorbing the remaining V2.5 goals.

---

### Phase 1: Data Restructuring & Feature Enrichment

**Goal:** Transition from static snapshots to temporal sequences and add forward-looking context.

* **The 3D Tensor Transformation:** Write a PyTorch `Dataset` and `DataLoader` to convert the existing 2D SQLite data into 3D sliding windows of shape `(batch_size, sequence_length, features)`.
* **Forward-Looking Features (V2.5 Milestone 8):** Before windowing, enrich the Pandas DataFrame with countdown features (e.g., `days_until_next_major`, `days_until_operation`). Neural networks excel at learning from these countdown signals.
* **Deep Learning Normalization:** Ensure strict scaling (like Min-Max or Layer Normalization) across the time steps, as LSTMs are highly sensitive to unscaled variance.

### Phase 2: Neural Architecture & Output Formulation

**Goal:** Build a model with "memory" capable of identifying regimes and bucketing predictions.

* **LSTM/GRU Core:** Implement a multi-layer Recurrent Neural Network. The hidden states of the LSTM will natively handle **Regime Detection (V2.5 Milestone 7)** by learning the velocity of volume and price changes leading up to an event.
* **Probability Bucketing (V2.5 Milestone 6):** Instead of forcing the model to predict an exact continuous log return, structure the final layer to output classification probabilities using a Softmax function.
* *Buckets:* Large Drop, Flat/Sideways, Break-Even (>15% fee), Massive Spike.



### Phase 3: Custom Loss Functions

**Goal:** Force the model to care about the "fat right tail" of the market.

* **Asymmetric Loss (V2.5 Milestone 7):** If predicting continuous returns, write a custom PyTorch loss function that penalizes the model heavily for missing a massive upward spike, but is forgiving if it misses standard market noise.
* **Cross-Entropy with Class Weights:** If using the Classification Bucket approach (Phase 2), apply class weights to the loss function to heavily penalize misclassifying a "Massive Spike" opportunity.

### Phase 4: Rigorous Evaluation & Backtest Integration

**Goal:** Prove the Deep Learning model outperforms the V2 Random Forest baseline in a realistic trading simulation.

* **Rolling-Window Validation (V2.5 Milestone 9):** Implement expanding window cross-validation (e.g., train on months 1-6, test on month 7) to ensure the LSTM isn't just memorizing one specific market regime.
* **V3 Backtest:** Plug the LSTM's predictions into the V2 backtester. Evaluate success not just on total balance, but on improvements in the **Sharpe Ratio**, **Sortino Ratio**, and **Maximum Drawdown**.
