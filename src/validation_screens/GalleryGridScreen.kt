package com.accessibility.test

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// =============================================================
// TELA DE VALIDAÇÃO #2 — GalleryGridScreen
// Violações intencionais (ground truth para validar o pipeline):
//
//   [LINT] IN #1 — Icon(Image, contentDescription = null) no loop da grade
//          Nota: Lint detecta 1 ocorrência de código (não 12 instâncias).
//          O ATF detecta as 12 instâncias renderizadas em tempo de execução.
//          Isso demonstra a diferença entre análise estática e dinâmica.
//
//   [ATF]  ST #1–12 — 12 itens de grade clicáveis sem texto acessível
//   [ATF]  ST #13–16 — 4 IconButtons: Modifier.size(28.dp) quebra a
//          propagação do contentDescription para o nó de acessibilidade pai,
//          gerando 4 violações ST adicionais. Total ATF: 16 ST.
//   [ATF]  TT: 0 — Material3 IconButton impõe minimumInteractiveComponentSize
//          = 48dp; o alvo de toque acessível é sempre 48dp independentemente
//          do Modifier.size visual. TouchTargetSizeCheck não é disparado.
//
// Total LINT: 1 IN
// Total ATF:  16 ST + 0 TT
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
    GalleryGridScreen()
}

@Composable
fun GalleryGridScreen() {
    Column(modifier = Modifier.fillMaxSize().padding(12.dp)) {
        Text("Galeria", fontSize = 20.sp, color = Color(0xFF212121))

        Spacer(Modifier.height(12.dp))

        // ST #13–16: IconButton com Modifier.size(28.dp). Material3 garante
        // minimumInteractiveComponentSize=48dp (TT=0), mas o override de tamanho
        // quebra a propagação do contentDescription → 4 violações ST no ATF.
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            repeat(4) {
                IconButton(
                    onClick = {},
                    modifier = Modifier.size(28.dp)
                ) {
                    Icon(
                        imageVector = Icons.Filled.FilterList,
                        contentDescription = "Filtro",
                        tint = Color(0xFF616161),
                        modifier = Modifier.size(16.dp)
                    )
                }
            }
        }

        Spacer(Modifier.height(16.dp))

        // Grade 4 linhas × 3 colunas = 12 itens
        // Cada item: clicável (ST) + Icon sem contentDescription (IN)
        for (row in 0 until 4) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                for (col in 0 until 3) {
                    Box(
                        modifier = Modifier
                            .size(96.dp)
                            .padding(3.dp)
                            .background(Color(0xFFE0E0E0))
                            .clickable {},
                        contentAlignment = Alignment.Center
                    ) {
                        // IN #${row * 3 + col + 1}: item de galeria sem descrição para leitores de tela
                        Icon(
                            imageVector = Icons.Filled.Image,
                            contentDescription = null,
                            tint = Color(0xFF9E9E9E),
                            modifier = Modifier.size(32.dp)
                        )
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}
