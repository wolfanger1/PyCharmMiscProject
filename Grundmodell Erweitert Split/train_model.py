import tensorflow as tf

# Beispiel-Modell erstellen
model = tf.keras.Sequential([
    tf.keras.Input(shape=(10,)),  # Besser: Input layer verwenden statt input_shape in Dense
    tf.keras.layers.Dense(16, activation="relu"),
    tf.keras.layers.Dense(1, activation="sigmoid")
])

# Kompiliere das Modell
model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

# Speichern im neuen nativen Keras-Format (.keras Datei)
model.save("mein_model.keras")
print("✅ Modell wurde als mein_model.keras gespeichert!")

