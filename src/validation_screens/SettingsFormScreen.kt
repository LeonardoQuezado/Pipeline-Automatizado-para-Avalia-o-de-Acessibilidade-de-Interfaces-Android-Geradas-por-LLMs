package com.accessibility.test

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// =============================================================
// TELA DE VALIDAÇÃO #3 — SettingsFormScreen
// Violações intencionais (ground truth para validar o pipeline):
//
//   [LINT] TF #1 — OutlinedTextField(username) sem parâmetro label
//   [LINT] TF #2 — OutlinedTextField(senha) sem parâmetro label
//   [LINT] TF #3 — OutlinedTextField(telefone) sem parâmetro label
//   [LINT] TF #4 — OutlinedTextField(cidade) sem parâmetro label
//   [LINT] IN #1 — Icon(Save, contentDescription = null) no botão salvar
//   [LINT] IN #2 — Icon(Visibility, contentDescription = null) no campo senha
//
// Total esperado LINT: 4 TF + 2 IN
// Total esperado ATF:  SpeakableTextPresentCheck nos campos e botões
// =============================================================

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    MainScreen()
                }
            }
        }
    }
}

@Composable
fun MainScreen() {
    SettingsFormScreen()
}

@Composable
fun SettingsFormScreen() {
    var username by remember { mutableStateOf("") }
    var senha by remember { mutableStateOf("") }
    var telefone by remember { mutableStateOf("") }
    var cidade by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize().padding(20.dp)) {
        Text("Configurações da Conta", fontSize = 20.sp, color = Color(0xFF212121))

        Spacer(Modifier.height(24.dp))

        // TF #1: OutlinedTextField sem label — não identificável por leitores de tela
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            placeholder = { Text("Nome de usuário") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(12.dp))

        // TF #2: OutlinedTextField sem label
        OutlinedTextField(
            value = senha,
            onValueChange = { senha = it },
            placeholder = { Text("Senha") },
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                IconButton(onClick = {}) {
                    // IN #2: ícone de visibilidade sem descrição acessível
                    Icon(imageVector = Icons.Filled.Visibility, contentDescription = null)
                }
            }
        )

        Spacer(Modifier.height(12.dp))

        // TF #3: OutlinedTextField sem label
        OutlinedTextField(
            value = telefone,
            onValueChange = { telefone = it },
            placeholder = { Text("Telefone") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(12.dp))

        // TF #4: OutlinedTextField sem label
        OutlinedTextField(
            value = cidade,
            onValueChange = { cidade = it },
            placeholder = { Text("Cidade") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {},
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2E7D32)),
            modifier = Modifier.fillMaxWidth()
        ) {
            // IN #1: ícone dentro do botão sem contentDescription
            Icon(imageVector = Icons.Filled.Save, contentDescription = null, tint = Color(0xFFFFFFFF))
            Spacer(Modifier.width(8.dp))
            Text("Salvar configurações", color = Color(0xFFFFFFFF))
        }
    }
}
