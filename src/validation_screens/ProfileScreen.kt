package com.accessibility.test

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// =============================================================
// TELA DE VALIDAÇÃO #1 — ProfileScreen
// Violações intencionais (ground truth para validar o pipeline):
//
//   [LINT] IN #1 — Icon(Person, contentDescription = null) no avatar
//   [LINT] IN #2 — Icon(Settings, contentDescription = null) no botão
//   [LINT] IN #3 — Icon(Share, contentDescription = null) no botão
//   [LINT] TF #1 — TextField(name) sem parâmetro label
//   [LINT] TF #2 — TextField(email) sem parâmetro label
//
// Total esperado LINT: 3 IN + 2 TF
// Total esperado ATF:  SpeakableTextPresentCheck nos IconButtons
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
    ProfileScreen()
}

@Composable
fun ProfileScreen() {
    var name by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(32.dp))

        Box(
            modifier = Modifier
                .size(80.dp)
                .clip(CircleShape)
                .background(Color(0xFF1565C0)),
            contentAlignment = Alignment.Center
        ) {
            // IN #1: leitor de tela não consegue anunciar o ícone
            Icon(
                imageVector = Icons.Filled.Person,
                contentDescription = null,
                tint = Color(0xFFFFFFFF),
                modifier = Modifier.size(40.dp)
            )
        }

        Spacer(Modifier.height(8.dp))
        Text("Usuário", fontSize = 18.sp, color = Color(0xFF212121))
        Spacer(Modifier.height(24.dp))

        // TF #1: campo não identificável por leitores de tela (sem label)
        TextField(
            value = name,
            onValueChange = { name = it },
            placeholder = { Text("Nome completo") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(12.dp))

        // TF #2: idem — placeholder não substitui label para acessibilidade
        TextField(
            value = email,
            onValueChange = { email = it },
            placeholder = { Text("E-mail") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(24.dp))

        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            // IN #2: botão sem descrição acessível
            IconButton(onClick = {}) {
                Icon(Icons.Filled.Settings, contentDescription = null, tint = Color(0xFF616161))
            }
            // IN #3: botão sem descrição acessível
            IconButton(onClick = {}) {
                Icon(Icons.Filled.Share, contentDescription = null, tint = Color(0xFF616161))
            }
        }

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {},
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1565C0)),
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Salvar perfil", color = Color(0xFFFFFFFF))
        }
    }
}
